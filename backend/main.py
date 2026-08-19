import os
import logging
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, WebSocket, UploadFile, File, HTTPException, WebSocketDisconnect
from starlette.websockets import WebSocketState
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
from typing import Optional, List

from services.repository_manager import RepositoryManager
from services.embedding_service import EmbeddingService
from services.ast_service import ASTService
from services.search_service import SearchService
from services.chat_service import ChatService
from services.code_completion_service import CodeCompletionService
from services.tool_executor import ToolExecutor
from services.agent_planner import AgentPlanner
from services.edit_history import EditHistory
from database.db import init_db, get_db
from api import repository_routes, chat_routes, search_routes, completion_routes
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global service instances
repository_manager: Optional[RepositoryManager] = None
embedding_service: Optional[EmbeddingService] = None
ast_service: Optional[ASTService] = None
search_service: Optional[SearchService] = None
chat_service: Optional[ChatService] = None
code_completion_service: Optional[CodeCompletionService] = None
tool_executor: Optional[ToolExecutor] = None
agent_planner: Optional[AgentPlanner] = None
edit_history: Optional[EditHistory] = None

class WriteFileBody(BaseModel):
    content: str

class ApplyEditItem(BaseModel):
    file_path: str
    proposed: str

class ApplyEditsBody(BaseModel):
    request_id: str
    edits: List[ApplyEditItem]

class UndoEditsBody(BaseModel):
    request_id: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, cleanup on shutdown"""
    global repository_manager, embedding_service, ast_service, search_service
    global chat_service, code_completion_service, tool_executor, agent_planner, edit_history
    
    logger.info("Initializing services...")
    
    # Initialize database
    await init_db()
    
    # Initialize services
    repository_manager = RepositoryManager()
    embedding_service = EmbeddingService()
    ast_service = ASTService()
    search_service = SearchService(embedding_service)
    chat_service = ChatService()
    code_completion_service = CodeCompletionService()
    tool_executor = ToolExecutor(
        repository_manager, ast_service, search_service, edit_history=None
    )
    # edit_history created next; wire after both exist
    edit_history = EditHistory()
    tool_executor.edit_history = edit_history
    agent_planner = AgentPlanner(tool_executor, chat_service)
    
    logger.info("Services initialized successfully")
    
    yield
    
    logger.info("Shutting down services...")
    await embedding_service.close()

app = FastAPI(
    title="AI Coding Assistant",
    description="Full-stack AI coding assistant with repository understanding",
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(repository_routes.router)
app.include_router(chat_routes.router)
app.include_router(search_routes.router)
app.include_router(completion_routes.router)

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}

@app.post("/api/upload-repository")
async def upload_repository(files: list[UploadFile] = File(...)):
    """
    Upload and index a repository.
    Accepts multiple files/folders.
    """
    try:
        repo_id = await repository_manager.process_upload(files)
        
        # Start indexing asynchronously
        asyncio.create_task(
            repository_manager.index_repository(repo_id)
        )
        
        return {
            "id": repo_id,
            "name": repo_id,
            "path": str(repository_manager.upload_dir / repo_id),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "status": "uploading",
            "message": "Repository uploaded. Indexing started..."
        }
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/repositories/{repo_id}/status")
async def repository_status(repo_id: str):
    """Get repository indexing status"""
    try:
        status = await repository_manager.get_repository_status(repo_id)
        return status
    except Exception as e:
        logger.error(f"Status error: {e}")
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/api/repositories/{repo_id}/files")
async def list_repository_files(repo_id: str):
    """List all files in repository"""
    try:
        files = await repository_manager.list_files(repo_id)
        return {"files": files}
    except Exception as e:
        logger.error(f"List files error: {e}")
        raise HTTPException(status_code=404, detail=str(e))

@app.get("/api/repositories/{repo_id}/file/{file_path:path}")
async def read_file(repo_id: str, file_path: str):
    """Read file content"""
    try:
        content = await repository_manager.read_file(repo_id, file_path)
        return {"path": file_path, "content": content}
    except Exception as e:
        logger.error(f"Read file error: {e}")
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/api/repositories/{repo_id}/file/{file_path:path}")
async def write_file(repo_id: str, file_path: str, body: WriteFileBody):
    """Write file content to disk"""
    try:
        result = await repository_manager.write_file(repo_id, file_path, body.content)
        return result
    except Exception as e:
        logger.error(f"Write file error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/repositories/{repo_id}/edits/apply")
async def apply_edits(repo_id: str, body: ApplyEditsBody):
    """Apply proposed edits after snapshotting current contents for undo."""
    if repo_id in ("local", "none", "__none__"):
        raise HTTPException(
            status_code=400,
            detail="Local sessions apply edits on the client",
        )
    try:
        snapshots = []
        applied = []
        for edit in body.edits:
            file_path = edit.file_path.replace("\\", "/")
            try:
                before = await repository_manager.read_file(repo_id, file_path)
            except FileNotFoundError:
                before = ""
            except Exception:
                before = ""

            snapshots.append({
                "file_path": file_path,
                "before": before,
                "after": edit.proposed,
            })
            await repository_manager.write_file(repo_id, file_path, edit.proposed)
            applied.append({"file_path": file_path, "status": "applied"})

        edit_history.save_snapshot(repo_id, body.request_id, snapshots)
        return {"applied": applied, "request_id": body.request_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Apply edits error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/repositories/{repo_id}/edits/undo")
async def undo_edits(repo_id: str, body: UndoEditsBody):
    """Restore files from the last apply snapshot for this request."""
    if repo_id in ("local", "none", "__none__"):
        raise HTTPException(
            status_code=400,
            detail="Local sessions undo edits on the client",
        )
    try:
        entry = edit_history.pop(repo_id, body.request_id)
        if not entry:
            raise HTTPException(status_code=404, detail="No undo snapshot for this request")

        undone = []
        for snap in entry.files:
            await repository_manager.write_file(repo_id, snap.file_path, snap.before)
            undone.append({"file_path": snap.file_path, "status": "undone"})

        return {"undone": undone, "request_id": body.request_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Undo edits error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.websocket("/ws/chat/{repo_id}")
async def websocket_chat(websocket: WebSocket, repo_id: str):
    """WebSocket endpoint for real-time chat with streaming responses"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            
            # Local session (no uploaded repo) gets empty context
            if repo_id in ("local", "none", "__none__"):
                repo_context = {"files": [], "total_files": 0, "languages": []}
            else:
                try:
                    repo_context = await repository_manager.get_repository_context(repo_id)
                except Exception:
                    repo_context = {"files": [], "total_files": 0, "languages": []}
            
            # Process chat with agent
            async for chunk in agent_planner.process_user_request(
                message=data.get("message"),
                repo_id=repo_id,
                context=repo_context,
                selected_file=data.get("selected_file"),
                selected_code=data.get("selected_code"),
                api_key=data.get("api_key"),
                model=data.get("model"),
                user_system_prompt=data.get("system_prompt"),
                enable_planning=bool(data.get("enable_planning")),
            ):
                await websocket.send_json(chunk)
                
    except WebSocketDisconnect:
        logger.debug("Chat client disconnected: %s", repo_id)
    except Exception as e:
        logger.exception("Chat WebSocket error")
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.send_json({"error": str(e), "type": "error"})
            except (WebSocketDisconnect, RuntimeError):
                pass
    finally:
        if websocket.application_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except RuntimeError:
                pass

@app.websocket("/ws/completion/{repo_id}")
async def websocket_completion(websocket: WebSocket, repo_id: str):
    """WebSocket endpoint for code completion with streaming"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            
            if repo_id in ("local", "none", "__none__"):
                repo_context = {"files": [], "total_files": 0, "languages": []}
            else:
                try:
                    repo_context = await repository_manager.get_repository_context(repo_id)
                except Exception:
                    repo_context = {"files": [], "total_files": 0, "languages": []}
            
            # Stream completion
            async for chunk in code_completion_service.stream_completion(
                prompt=data.get("prompt"),
                file_path=data.get("file_path"),
                repo_context=repo_context,
                language=data.get("language", "javascript"),
                api_key=data.get("api_key"),
                model=data.get("model"),
                user_system_prompt=data.get("system_prompt"),
                suffix=data.get("suffix") or "",
            ):
                if isinstance(chunk, str):
                    await websocket.send_json(json.loads(chunk))
                else:
                    await websocket.send_json(chunk)
                
    except WebSocketDisconnect:
        logger.debug("Completion client disconnected: %s", repo_id)
    except Exception as e:
        logger.exception("Completion WebSocket error")
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.send_json({"error": str(e), "type": "error"})
            except (WebSocketDisconnect, RuntimeError):
                pass
    finally:
        if websocket.application_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except RuntimeError:
                pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
