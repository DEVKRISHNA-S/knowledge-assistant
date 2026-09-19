"""
SQLAlchemy models — the normalized schema every source writes into.
This is the boundary: connectors/ produce RawItems, this schema stores them
uniformly regardless of source.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, DateTime, Integer, JSON, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    title = Column(Text, nullable=False)
    raw_content = Column(Text, nullable=False)
    cleaned_content = Column(Text, nullable=True)
    permission_scope = Column(String, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, index=True)
    doc_metadata = Column(JSON, default=dict)
    indexed_at = Column(DateTime(timezone=True), nullable=True)

    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_source_source_id"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=True)
    qdrant_point_id = Column(String, nullable=True, index=True)

    document = relationship("Document", back_populates="chunks")


class SyncState(Base):
    __tablename__ = "sync_state"

    source = Column(String, primary_key=True)
    cursor = Column(String, nullable=True)
    last_run_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))