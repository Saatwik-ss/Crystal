from fastapi import APIRouter, HTTPException
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/completion", tags=["completion"])

# WebSocket handlers in main.py