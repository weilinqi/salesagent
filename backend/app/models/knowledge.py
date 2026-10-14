"""Persistent knowledge ingestion records; vector contents live in ChromaDB."""
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from app.database import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(255), nullable=False)
    source_type = Column(String(20), nullable=False, default="pdf")
    category = Column(String(128), nullable=False, index=True)
    # Internal, root-relative path. Never included in an API response.
    file_path = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="queued", index=True)
    chunk_count = Column(Integer, nullable=False, default=0)
    error = Column(String(250), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
