# backend/app/models/knowledge.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from app.core.database import Base

class Document(Base):
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(256))
    file_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="parsing")  # parsing/ready/failed
    uploader_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    department_id: Mapped[str | None] = mapped_column(String(36), index=True)  # 逻辑外键
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan",
        foreign_keys="Chunk.document_id",
    )

class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    seq: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    meta_: Mapped[dict | None] = mapped_column("meta", JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    document: Mapped[Document] = relationship(back_populates="chunks", foreign_keys=[document_id])