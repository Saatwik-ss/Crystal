
import os
import shutil
import asyncio
import threading
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime
import logging
from sqlalchemy import select
from fastapi import UploadFile
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import uuid
from database.db import get_db
from database.models import Repository, RepositoryFile, IndexingStatus
from .ast_service import ASTService
from .embedding_service import EmbeddingService
from .chunking_service import ChunkingService
logger = logging.getLogger(__name__)
UPLOAD_DIR = Path(os.getenv('UPLOAD_DIR', str((Path(tempfile.gettempdir()) / 'ai_assistant_repos'))))
IGNORE_DIRS = {'node_modules', '.git', 'dist', 'build', 'venv', '__pycache__', '.venv', '.next', '.nuxt', '.cache', '.pytest_cache', '.mypy_cache'}
IGNORE_FILES = {'.DS_Store', '*.pyc', '*.pyo', '*.pyd', '__pycache__', '.env'}

class RepositoryFileWatcher(FileSystemEventHandler):
    """Watch repository for changes and trigger re-indexing"""

    def __init__(self, repo_id: str, callback, loop: Optional[asyncio.AbstractEventLoop] = None):
        self.repo_id = repo_id
        self.callback = callback
        self.loop = loop
        self.debounce_timer: Optional[threading.Timer] = None

    def on_modified(self, event):
        if event.is_directory:
            return
        if self.debounce_timer:
            self.debounce_timer.cancel()
        self.debounce_timer = threading.Timer(2.0, self._trigger)
        self.debounce_timer.start()

    def _trigger(self):
        try:
            target_loop = self.loop
            if target_loop is None or not target_loop.is_running():
                target_loop = asyncio.get_event_loop()
            if target_loop.is_running():
                asyncio.run_coroutine_threadsafe(self.callback(self.repo_id), target_loop)
            else:
                target_loop.run_until_complete(self.callback(self.repo_id))
        except Exception as e:
            logger.error(f"Error triggering re-index for {self.repo_id}: {e}")

INDEX_COMMIT_BATCH = 50
MAX_INDEX_ERRORS = 50

class RepositoryManager():

    def __init__(self, embedding_service: Optional[EmbeddingService] = None):
        self.upload_dir = UPLOAD_DIR
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.watchers: Dict[(str, Observer)] = {}
        self.indexing_status: Dict[(str, Dict[(str, Any)])] = {}
        self.embedding_service = embedding_service

    async def process_upload(self, files: List[UploadFile]) -> str:
        """Process uploaded files and create repository with immediate file records"""
        repo_id = str(uuid.uuid4())
        repo_path = (self.upload_dir / repo_id)
        repo_path.mkdir(parents=True, exist_ok=True)
        file_records = []
        for idx, file in enumerate(files):
            relative_name = file.filename.replace('\\', '/')
            file_path = (repo_path / relative_name)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            contents = await file.read()
            with open(file_path, 'wb') as f:
                f.write(contents)
            ext = Path(relative_name).suffix.lower()
            file_records.append(
                RepositoryFile(
                    repository_id=repo_id,
                    path=str(relative_name),
                    language=self._get_language(ext),
                    content_hash=self._hash_content(contents.decode('utf-8', errors='ignore')),
                    size=len(contents),
                )
            )
            if idx % 25 == 24:
                await asyncio.sleep(0)
        db = await get_db()
        try:
            repository = Repository(id=repo_id, name=repo_id, path=str(repo_path), created_at=datetime.utcnow())
            db.add(repository)
            for rf in file_records:
                db.add(rf)
            await db.commit()
            self.indexing_status[repo_id] = {
                'status': 'initializing',
                'files_processed': 0,
                'total_files': len(file_records),
                'errors': []
            }
            logger.info(f'Repository {repo_id} uploaded with {len(file_records)} files to {repo_path}')
            return repo_id
        finally:
            await db.close()

    def _record_index_error(self, repo_id: str, message: str) -> None:
        errors = self.indexing_status.setdefault(repo_id, {}).setdefault('errors', [])
        if len(errors) < MAX_INDEX_ERRORS:
            errors.append(message)

    async def index_repository(self, repo_id: str) -> None:
        """
        Index repository: generate AST, embeddings, and dependency graph.
        Files are already populated in DB during process_upload.
        """
        db = None
        try:
            if repo_id not in self.indexing_status:
                self.indexing_status[repo_id] = {
                    'status': 'indexing',
                    'files_processed': 0,
                    'total_files': 0,
                    'errors': [],
                }
            repo_path = (self.upload_dir / repo_id)
            self.indexing_status[repo_id]['status'] = 'indexing'
            files = await self._traverse_repository(repo_path)
            self.indexing_status[repo_id]['total_files'] = len(files)
            db = await get_db()
            ast_service = ASTService()
            embedding_service = self.embedding_service or EmbeddingService()
            chunking_service = ChunkingService(ast_service)
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, embedding_service.reset_collection, repo_id)
            except Exception as reset_err:
                logger.warning(f"Could not reset Chroma collection for {repo_id}: {reset_err}")

            SKIP_EMBED_FILENAMES = {
                'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'cargo.lock',
                'poetry.lock', 'pipfile.lock', 'composer.lock', 'gemfile.lock'
            }
            SKIP_EMBED_SUFFIXES = {
                '.min.js', '.min.css', '.map', '.bundle.js', '.chunk.js',
                '.lock', '.csv', '.tsv', '.jsonl'
            }

            pending_since_commit = 0
            for (idx, file_path) in enumerate(files):
                try:
                    relative_path = file_path.relative_to(repo_path).as_posix()
                    file_size = file_path.stat().st_size
                    content = await loop.run_in_executor(
                        None,
                        lambda p=file_path: p.read_text(encoding='utf-8', errors='ignore'),
                    )
                    ext = file_path.suffix.lower()
                    language = self._get_language(ext)
                    ast_data = None
                    if language in ['python', 'javascript', 'typescript'] and file_size < 300 * 1024:
                        try:
                            ast_data = await loop.run_in_executor(
                                None, ast_service.parse_file, content, language
                            )
                        except Exception as ast_err:
                            logger.warning(f"AST parsing failed for {relative_path}: {ast_err}")

                    existing = (await db.scalars(
                        select(RepositoryFile).where(
                            RepositoryFile.repository_id == repo_id,
                            RepositoryFile.path == str(relative_path)
                        )
                    )).first()

                    if existing:
                        existing.language = language
                        existing.content_hash = self._hash_content(content)
                        existing.ast_data = ast_data
                        existing.size = len(content)
                    else:
                        repo_file = RepositoryFile(
                            repository_id=repo_id,
                            path=str(relative_path),
                            language=language,
                            content_hash=self._hash_content(content),
                            ast_data=ast_data,
                            size=len(content)
                        )
                        db.add(repo_file)

                    should_skip_embed = (
                        file_path.name.lower() in SKIP_EMBED_FILENAMES
                        or any(file_path.name.lower().endswith(s) for s in SKIP_EMBED_SUFFIXES)
                        or file_size > 300 * 1024
                    )

                    if not should_skip_embed:
                        try:
                            chunks = chunking_service.chunk_file(content, str(relative_path), language, ast_data)
                            if chunks:
                                await embedding_service.store_symbol_embeddings(repo_id, chunks[:20])
                        except Exception as emb_err:
                            logger.warning(f"Embedding failed for {relative_path}: {emb_err}")
                            self._record_index_error(repo_id, f"{relative_path}: {emb_err}")

                    pending_since_commit += 1
                    if pending_since_commit >= INDEX_COMMIT_BATCH:
                        await db.commit()
                        pending_since_commit = 0

                    self.indexing_status[repo_id]['files_processed'] = (idx + 1)
                except Exception as e:
                    logger.error(f'Error processing file {file_path}: {e}')
                    self._record_index_error(repo_id, str(e))
                    self.indexing_status[repo_id]['files_processed'] = (idx + 1)

                await asyncio.sleep(0)

            if pending_since_commit:
                await db.commit()
            try:
                await self._build_dependency_graph(repo_id)
            except Exception as dg_err:
                logger.warning(f"Dependency graph building failed: {dg_err}")

            self.indexing_status[repo_id]['status'] = 'completed'
            logger.info(f'Repository {repo_id} indexing completed successfully')
        except Exception as e:
            logger.error(f'Repository indexing failed for {repo_id}: {e}')
            if repo_id in self.indexing_status:
                self.indexing_status[repo_id]['status'] = 'failed'
                self.indexing_status[repo_id]['error'] = str(e)
        finally:
            if db:
                await db.close()

    BINARY_EXTENSIONS = {
        '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp', '.bmp', '.tiff',
        '.exe', '.dll', '.so', '.dylib', '.bin', '.obj', '.o', '.a', '.lib',
        '.zip', '.tar', '.gz', '.tgz', '.bz2', '.7z', '.rar', '.iso',
        '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx',
        '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv', '.webm',
        '.woff', '.woff2', '.ttf', '.eot', '.otf',
        '.pyc', '.pyo', '.pyd', '.class', '.jar', '.war',
        '.db', '.sqlite', '.sqlite3',
    }

    async def _traverse_repository(self, repo_path: Path) -> List[Path]:
        """Recursively traverse repository and collect code and text files."""

        def should_ignore(path: Path) -> bool:
            for part in path.parts:
                if part in IGNORE_DIRS:
                    return True
                if part.startswith('.') and part != '.' and not part.startswith('.env') and not part.startswith('.git'):
                    return True
            if path.is_dir():
                return False
            if path.suffix.lower() in self.BINARY_EXTENSIONS:
                return True
            if path.name in IGNORE_FILES:
                return True
            try:
                if path.stat().st_size > 5 * 1024 * 1024:
                    return True
            except Exception:
                return True
            return False

        def collect() -> List[Path]:
            files = []
            for item in repo_path.rglob('*'):
                if item.is_file() and not should_ignore(item):
                    files.append(item)
            return sorted(files)

        return await asyncio.get_running_loop().run_in_executor(None, collect)

    def _get_language(self, extension: str) -> str:
        """Map file extension to language"""
        ext = (extension or "").lower()
        ext_map = {
            '.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.tsx': 'typescript',
            '.jsx': 'javascript', '.java': 'java', '.cpp': 'cpp', '.c': 'c', '.h': 'c',
            '.hpp': 'cpp', '.go': 'go', '.rs': 'rust', '.rb': 'ruby', '.php': 'php',
            '.swift': 'swift', '.kt': 'kotlin', '.scala': 'scala', '.cs': 'csharp',
            '.dart': 'dart', '.html': 'html', '.htm': 'html', '.css': 'css',
            '.scss': 'scss', '.less': 'less', '.json': 'json', '.md': 'markdown',
            '.markdown': 'markdown', '.txt': 'plaintext', '.yaml': 'yaml', '.yml': 'yaml',
            '.xml': 'xml', '.sql': 'sql', '.sh': 'bash', '.bash': 'bash', '.zsh': 'bash',
            '.ps1': 'powershell', '.bat': 'batch', '.vue': 'vue', '.svelte': 'svelte',
            '.toml': 'toml', '.ini': 'ini', '.lua': 'lua', '.r': 'r',
        }
        return ext_map.get(ext, 'plaintext')

    def _chunk_file(self, content: str, file_path: Path, chunk_size: int=1000) -> List[str]:
        'Split file content into chunks for embedding'
        chunks = []
        lines = content.split('\n')
        current_chunk = []
        current_length = 0
        for line in lines:
            current_chunk.append(line)
            current_length += len(line)
            if (current_length > chunk_size):
                chunks.append('\n'.join(current_chunk))
                current_chunk = []
                current_length = 0
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        return chunks

    def _hash_content(self, content: str) -> str:
        'Generate hash of content for change detection'
        import hashlib
        return hashlib.sha256(content.encode()).hexdigest()

    async def _build_dependency_graph(self, repo_id: str) -> None:
        'Build dependency graph for repository'
        db = None
        try:
            db = (await get_db())
            ast_service = ASTService()
            files = (await db.scalars(select(RepositoryFile).where((RepositoryFile.repository_id == repo_id), (RepositoryFile.language == 'python')))).all()
            dependency_graph = {}
            for file in files:
                repo_path = (self.upload_dir / repo_id)
                file_path = (repo_path / file.path)
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                ast_data = ast_service.parse_file(content, 'python')
                if ast_data:
                    imports = ast_data.get('imports', [])
                    dependency_graph[file.path] = imports
            repository = (await db.get(Repository, repo_id))
            if repository:
                repository.repo_metadata = {'dependencies': dependency_graph}
            (await db.commit())
        except Exception as e:
            logger.error(f'Dependency graph building failed: {e}')
        finally:
            if db:
                await db.close()

    def _start_file_watcher(self, repo_id: str, repo_path: Path) -> None:
        """Start file watcher for automatic re-indexing"""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            event_handler = RepositoryFileWatcher(repo_id, self.index_repository, loop=loop)
            observer = Observer()
            observer.schedule(event_handler, str(repo_path), recursive=True)
            observer.start()
            self.watchers[repo_id] = observer
            logger.info(f'File watcher started for {repo_id}')
        except Exception as e:
            logger.error(f'Failed to start file watcher: {e}')

    async def get_repository_status(self, repo_id: str) -> Dict[(str, Any)]:
        'Get current indexing status'
        status = self.indexing_status.get(repo_id, {})
        return {'repository_id': repo_id, **status}

    async def list_files(self, repo_id: str) -> List[Dict[(str, Any)]]:
        'List all files in repository'
        db = (await get_db())
        try:
            rows = (await db.execute(
                select(RepositoryFile.path, RepositoryFile.language, RepositoryFile.size).where(
                    (RepositoryFile.repository_id == repo_id)
                )
            )).all()
            return [{'path': r.path, 'language': r.language, 'size': r.size} for r in rows]
        finally:
            (await db.close())

    async def read_file(self, repo_id: str, file_path: str) -> str:
        'Read file content from repository'
        file_path = file_path.replace('\\', '/')
        db = (await get_db())
        try:
            repo_file = (await db.scalars(select(RepositoryFile).where((RepositoryFile.repository_id == repo_id), (RepositoryFile.path == file_path)))).first()
            if (not repo_file):
                raise FileNotFoundError(f'File not found: {file_path}')
            full_path = ((self.upload_dir / repo_id) / file_path)
            return full_path.read_text(encoding='utf-8', errors='ignore')
        finally:
            (await db.close())

    async def write_file(self, repo_id: str, file_path: str, content: str) -> Dict[(str, Any)]:
        'Write content to file and update database'
        full_path = ((self.upload_dir / repo_id) / file_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding='utf-8')
        db = (await get_db())
        try:
            file_path_clean = file_path.replace('\\', '/')
            repo_file = (await db.scalars(select(RepositoryFile).where((RepositoryFile.repository_id == repo_id), (RepositoryFile.path == file_path_clean)))).first()
            ext = Path(file_path_clean).suffix.lower()
            language = self._get_language(ext)
            if repo_file:
                repo_file.content_hash = self._hash_content(content)
                repo_file.size = len(content)
                repo_file.language = language
            else:
                repo_file = RepositoryFile(
                    repository_id=repo_id,
                    path=file_path_clean,
                    language=language,
                    content_hash=self._hash_content(content),
                    ast_data=None,
                    size=len(content)
                )
                db.add(repo_file)
            (await db.commit())
            return {'path': file_path_clean, 'status': 'saved', 'size': len(content)}
        finally:
            (await db.close())

    async def get_repository_context(self, repo_id: str) -> Dict[(str, Any)]:
        'Get comprehensive repository context for LLM'
        db = (await get_db())
        try:
            rows = (await db.execute(
                select(RepositoryFile.path, RepositoryFile.language).where(
                    (RepositoryFile.repository_id == repo_id)
                )
            )).all()
            files = [{'path': r.path, 'language': r.language} for r in rows]
            languages = list({r.language for r in rows if r.language})
            return {'files': files, 'total_files': len(files), 'languages': languages}
        finally:
            (await db.close())

    def cleanup(self, repo_id: str) -> None:
        'Clean up repository and stop file watcher'
        if (repo_id in self.watchers):
            self.watchers[repo_id].stop()
            self.watchers[repo_id].join()
            del self.watchers[repo_id]
        repo_path = (self.upload_dir / repo_id)
        if repo_path.exists():
            shutil.rmtree(repo_path)
