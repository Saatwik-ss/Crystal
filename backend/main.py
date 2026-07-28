import os
import logging
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
from typing import Optional

from services.repository_manager import RepositoryManager
from services.embedding_service import EmbeddingService
from services.ast_service import ASTService
from services.search_service import SearchService
from services.chat_service import ChatService
from services.code_completion_service import CodeCompletionService
from services.tool_executor import ToolExecutor
from services.agent_planner import AgentPlanner
from database.db import init_db, get_db
from api import repository_routes, chat_routes, search_routes, completion_routes

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup, cleanup on shutdown"""
    global repository_manager, embedding_service, ast_service, search_service
    global chat_service, code_completion_service, tool_executor, agent_planner
    
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
    tool_executor = ToolExecutor(repository_manager, ast_service, search_service)
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

@app.websocket("/ws/chat/{repo_id}")
async def websocket_chat(websocket: WebSocket, repo_id: str):
    """WebSocket endpoint for real-time chat with streaming responses"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            
            # Get repository context
            repo_context = await repository_manager.get_repository_context(repo_id)
            
            # Process chat with agent
            async for chunk in agent_planner.process_user_request(
                message=data.get("message"),
                repo_id=repo_id,
                context=repo_context,
                selected_file=data.get("selected_file"),
                selected_code=data.get("selected_code")
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
            
            # Get repository context for better completions
            repo_context = await repository_manager.get_repository_context(repo_id)
            
            # Stream completion
            async for chunk in code_completion_service.stream_completion(
                prompt=data.get("prompt"),
                file_path=data.get("file_path"),
                repo_context=repo_context,
                language=data.get("language", "javascript")
            ):
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
