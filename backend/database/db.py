import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

from .models import Base

logger = logging.getLogger(__name__)

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./ai_assistant.db"
)

# Create async engine
engine = None
async_session_maker = None

async def init_db():
    """Initialize database connection and create tables"""
    global engine, async_session_maker
    
    try:
        logger.info(f"Initializing database: {DATABASE_URL}")
        
        # Create engine
        engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            future=True
        )
        
        # Create session factory
        async_session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # Create tables
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("Database initialized successfully")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

async def get_db() -> AsyncSession:
    """Get database session"""
    if async_session_maker is None:
        raise RuntimeError("Database not initialized. Call init_db() first")
    
    return async_session_maker()

async def close_db():
    """Close database connection"""
    if engine:
        await engine.dispose()
        logger.info("Database connection closed")