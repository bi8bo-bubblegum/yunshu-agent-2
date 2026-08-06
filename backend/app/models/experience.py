# backend/app/models/experience.py
from datetime import date, datetime
from uuid import uuid4
from sqlalchemy import UUID, Date, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from app.core.database import Base

class Experience(Base):
    __tablename__ = "experiences"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    scope: Mapped[str] = mapped_column(String(16))  # personal/dept/company
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft/pending/approved/rejected
    title: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    event_time: Mapped[date | None] = mapped_column(Date)
    result_metrics: Mapped[dict | None] = mapped_column(JSONB)
    department_id: Mapped[str | None] = mapped_column(String(36), index=True)  # 逻辑外键
    source_trace_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
