from fastapi import APIRouter, HTTPException, Query
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])

# Search endpoints handled in main.py or can be expanded here