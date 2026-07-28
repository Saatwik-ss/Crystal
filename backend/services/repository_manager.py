import os
import shutil
import asyncio
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime
import logging
import json
from sqlalchemy import select
from fastapi import UploadFile
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import uuid

from database.db import get_db
from database.models import Repository, RepositoryFile, IndexingStatus
from .ast_service import ASTService
from .embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(Path(tempfile.gettempdir()) / "ai_assistant_repos")))
IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", "venv", "__pycache__",
    ".venv", ".next", ".nuxt", ".cache", ".pytest_cache", ".mypy_cache"
}
IGNORE_FILES = {
    ".DS_Store", "*.pyc", "*.pyo", "*.pyd", "__pycache__", ".env"
}

class RepositoryFileWatcher(FileSystemEventHandler):
    """Watch repository for changes and trigger re-indexing"""
    
    def __init__(self, repo_id: str, callback):
        self.repo_id = repo_id
        self.callback = callback
        self.debounce_timer = None
    
    def on_modified(self, event):
        if event.is_directory:
            return
        # Debounce file changes
        if self.debounce_timer:
            self.debounce_timer.cancel()
        self.debounce_timer = asyncio.Timer(2.0, lambda: self.callback(self.repo_id))
        self.debounce_timer.start()

class RepositoryManager:
    def __init__(self):
        self.upload_dir = UPLOAD_DIR
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.watchers: Dict[str, Observer] = {}
        self.indexing_status: Dict[str, Dict[str, Any]] = {}
    
    async def process_upload(self, files: List[UploadFile]) -> str:
        """Process uploaded files and create repository"""
        repo_id = str(uuid.uuid4())
        repo_path = self.upload_dir / repo_id
        repo_path.mkdir(parents=True, exist_ok=True)
        
        # Save uploaded files
        for file in files:
            relative_name = file.filename.replace("\\", "/")
            file_path = repo_path / relative_name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            contents = await file.read()
            with open(file_path, "wb") as f:
                f.write(contents)
        
        # Initialize repository in database
        db = await get_db()
        
        repository = Repository(
            id=repo_id,
            name=repo_id,
            path=str(repo_path),
            created_at=datetime.utcnow()
        )
        db.add(repository)
        await db.commit()
        
        # Initialize indexing status
        self.indexing_status[repo_id] = {
            "status": "initializing",
            "files_processed": 0,
            "total_files": 0,
            "errors": []
        }
        
        logger.info(f"Repository {repo_id} uploaded to {repo_path}")
        return repo_id
    
    async def index_repository(self, repo_id: str) -> None:
        """
        Index repository: traverse files, generate AST, embeddings, and dependency graph
        """
        try:
            repo_path = self.upload_dir / repo_id
            self.indexing_status[repo_id]["status"] = "indexing"
            
            # Get all files
            files = await self._traverse_repository(repo_path)
            self.indexing_status[repo_id]["total_files"] = len(files)
            
            db = await get_db()
            ast_service = ASTService()
            embedding_service = EmbeddingService()
            
            # Process each file
            for idx, file_path in enumerate(files):
                try:
                    relative_path = file_path.relative_to(repo_path).as_posix()
                    content = file_path.read_text(encoding='utf-8', errors='ignore')
                    
                    # Determine file type and language
                    ext = file_path.suffix
                    language = self._get_language(ext)
                    
                    # Generate AST
                    ast_data = None
                    if language in ["python", "javascript", "typescript"]:
                        ast_data = ast_service.parse_file(content, language)
                    
                    # Create file record
                    repo_file = RepositoryFile(
                        repository_id=repo_id,
                        path=str(relative_path),
                        language=language,
                        content_hash=self._hash_content(content),
                        ast_data=json.dumps(ast_data) if ast_data else None,
                        size=len(content)
                    )
                    db.add(repo_file)
                    
                    # Generate embeddings for file chunks
                    chunks = self._chunk_file(content, file_path)
                    if chunks:
                        await embedding_service.store_file_embeddings(
                            repo_id,
                            str(relative_path),
                            chunks,
                        )
                    # #region agent log
                    from debug_log import debug_log
                    debug_log("A", "repository_manager.py:index_repository", "chunked file during indexing", {
                        "repo_id": repo_id,
                        "relative_path": str(relative_path),
                        "chunk_count": len(chunks),
                        "stored_to_chroma": bool(chunks),
                    })
                    # #endregion
                    
                    self.indexing_status[repo_id]["files_processed"] = idx + 1
                    
                except Exception as e:
                    logger.error(f"Error processing file {file_path}: {e}")
                    self.indexing_status[repo_id]["errors"].append(str(e))
            
            await db.commit()
            
            # Build dependency graph
            await self._build_dependency_graph(repo_id)
            
            self.indexing_status[repo_id]["status"] = "completed"
            logger.info(f"Repository {repo_id} indexing completed")
            
            # Start file watcher for auto-reindex
            self._start_file_watcher(repo_id, repo_path)
            
        except Exception as e:
            logger.error(f"Repository indexing failed for {repo_id}: {e}")
            self.indexing_status[repo_id]["status"] = "failed"
            self.indexing_status[repo_id]["error"] = str(e)
    
    async def _traverse_repository(self, repo_path: Path) -> List[Path]:
        """Recursively traverse repository and collect code files"""
        files = []
        code_extensions = {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cpp", ".c",
            ".h", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala"
        }
        
        def should_ignore(path: Path) -> bool:
            if path.is_dir():
                return path.name in IGNORE_DIRS or path.name.startswith('.')
            return path.suffix not in code_extensions
        
        for item in repo_path.rglob("*"):
            if should_ignore(item):
                continue
            if item.is_file():
                files.append(item)
        
        return sorted(files)
    
    def _get_language(self, extension: str) -> str:
        """Map file extension to language"""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".php": "php",
            ".swift": "swift",
            ".kt": "kotlin",
        }
        return ext_map.get(extension, "unknown")
    
    def _chunk_file(self, content: str, file_path: Path, chunk_size: int = 1000) -> List[str]:
        """Split file content into chunks for embedding"""
        chunks = []
        lines = content.split('\n')
        current_chunk = []
        current_length = 0
        
        for line in lines:
            current_chunk.append(line)
            current_length += len(line)
            
            if current_length > chunk_size:
                chunks.append('\n'.join(current_chunk))
                current_chunk = []
                current_length = 0
        
        if current_chunk:
            chunks.append('\n'.join(current_chunk))
        
        return chunks
    
    def _hash_content(self, content: str) -> str:
        """Generate hash of content for change detection"""
        import hashlib
        return hashlib.sha256(content.encode()).hexdigest()
    
    async def _build_dependency_graph(self, repo_id: str) -> None:
        """Build dependency graph for repository"""
        try:
            db = await get_db()
            ast_service = ASTService()
            
            # Get all Python files
            files = (await db.scalars(select(RepositoryFile).where(
                RepositoryFile.repository_id == repo_id,
                RepositoryFile.language == "python"
            ))).all()
            
            dependency_graph = {}
            
            for file in files:
                repo_path = self.upload_dir / repo_id
                file_path = repo_path / file.path
                
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                ast_data = ast_service.parse_file(content, "python")
                
                if ast_data:
                    imports = ast_data.get("imports", [])
                    dependency_graph[file.path] = imports
            
            # Store in repository metadata
            repository = await db.get(Repository, repo_id)
            if repository:
                repository.repo_metadata = {"dependencies": dependency_graph}
            await db.commit()
            
        except Exception as e:
            logger.error(f"Dependency graph building failed: {e}")
    
    def _start_file_watcher(self, repo_id: str, repo_path: Path) -> None:
        """Start file watcher for automatic re-indexing"""
        try:
            event_handler = RepositoryFileWatcher(
                repo_id,
                lambda rid: asyncio.create_task(self.index_repository(rid))
            )
            observer = Observer()
            observer.schedule(event_handler, str(repo_path), recursive=True)
            observer.start()
            self.watchers[repo_id] = observer
            logger.info(f"File watcher started for {repo_id}")
        except Exception as e:
            logger.error(f"Failed to start file watcher: {e}")
    
    async def get_repository_status(self, repo_id: str) -> Dict[str, Any]:
        """Get current indexing status"""
        status = self.indexing_status.get(repo_id, {})
        return {
            "repository_id": repo_id,
            **status
        }
    
    async def list_files(self, repo_id: str) -> List[Dict[str, Any]]:
        """List all files in repository"""
        db = await get_db()
        files = (await db.scalars(select(RepositoryFile).where(
            RepositoryFile.repository_id == repo_id
        ))).all()
        
        return [
            {
                "path": f.path,
                "language": f.language,
                "size": f.size
            }
            for f in files
        ]
    
    async def read_file(self, repo_id: str, file_path: str) -> str:
        """Read file content from repository"""
        file_path = file_path.replace("\\", "/")
        db = await get_db()
        repo_file = (await db.scalars(select(RepositoryFile).where(
            RepositoryFile.repository_id == repo_id,
            RepositoryFile.path == file_path
        ))).first()
        
        if not repo_file:
            raise FileNotFoundError(f"File not found: {file_path}")
        
        full_path = self.upload_dir / repo_id / file_path
        return full_path.read_text(encoding='utf-8', errors='ignore')
    
    async def write_file(self, repo_id: str, file_path: str, content: str) -> Dict[str, Any]:
        """Write content to file and update database"""
        full_path = self.upload_dir / repo_id / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding='utf-8')
        
        # Update file record
        db = await get_db()
        repo_file = (await db.scalars(select(RepositoryFile).where(
            RepositoryFile.repository_id == repo_id,
            RepositoryFile.path == file_path
        ))).first()
        
        if repo_file:
            repo_file.content_hash = self._hash_content(content)
            repo_file.size = len(content)
        
        await db.commit()
        
        return {
            "path": file_path,
            "status": "saved",
            "size": len(content)
        }
    
    async def get_repository_context(self, repo_id: str) -> Dict[str, Any]:
        """Get comprehensive repository context for LLM"""
        db = await get_db()
        
        files = (await db.scalars(select(RepositoryFile).where(
            RepositoryFile.repository_id == repo_id
        ))).all()
        
        context = {
            "files": [
                {
                    "path": f.path,
                    "language": f.language,
                    "ast": json.loads(f.ast_data) if f.ast_data else None
                }
                for f in files
            ],
            "total_files": len(files),
            "languages": list(set(f.language for f in files))
        }
        
        return context
    
    def cleanup(self, repo_id: str) -> None:
        """Clean up repository and stop file watcher"""
        if repo_id in self.watchers:
            self.watchers[repo_id].stop()
            self.watchers[repo_id].join()
            del self.watchers[repo_id]
        
        repo_path = self.upload_dir / repo_id
        if repo_path.exists():
            shutil.rmtree(repo_path)
