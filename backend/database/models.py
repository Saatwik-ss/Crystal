from sqlalchemy import Column, String, Integer, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()

class Repository(Base):
    """Repository metadata"""
    __tablename__ = "repositories"
    
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    path = Column(String, nullable=False)
    repo_metadata = Column("metadata", JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class RepositoryFile(Base):
    """File metadata in repository"""
    __tablename__ = "repository_files"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False)
    path = Column(String, nullable=False)
    language = Column(String)
    content_hash = Column(String)
    ast_data = Column(JSON)
    size = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class IndexingStatus(Base):
    """Tracking indexing status"""
    __tablename__ = "indexing_status"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False)
    status = Column(String)  # "pending", "indexing", "completed", "failed"
    files_processed = Column(Integer, default=0)
    total_files = Column(Integer, default=0)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class CodeSnapshot(Base):
    """Version control - snapshots of repository state"""
    __tablename__ = "code_snapshots"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    repository_id = Column(String, ForeignKey("repositories.id"), nullable=False)
    description = Column(String)
    changes = Column(JSON)  # List of file changes
    diff = Column(Text)  # Unified diff
    created_at = Column(DateTime, default=datetime.utcnow)