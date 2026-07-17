from fastapi import APIRouter, HTTPException
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/repositories", tags=["repositories"])

# Routes are handled in main.py for now
# This file can be extended for additional repository endpoints