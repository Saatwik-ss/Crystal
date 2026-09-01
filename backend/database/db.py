import os
import logging
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

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


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


async def init_db():
    """Initialize database connection and create tables"""
    global engine, async_session_maker

    try:
        logger.info(f"Initializing database: {DATABASE_URL}")

        connect_args = {}
        if _is_sqlite(DATABASE_URL):
            connect_args = {"timeout": 30}

        engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            future=True,
            connect_args=connect_args,
        )

        if _is_sqlite(DATABASE_URL):
            @event.listens_for(engine.sync_engine, "connect")
            def _set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.close()

        async_session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if _is_sqlite(DATABASE_URL):
                await conn.execute(text("PRAGMA journal_mode=WAL"))
                await conn.execute(text("PRAGMA busy_timeout=30000"))

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
