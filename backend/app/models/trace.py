# backend/app/models/trace.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, BigInteger, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class ExecutionTrace(Base):
    __tablename__ = "execution_traces"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    conversation_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/completed/interrupted/failed
    supervisor_routes: Mapped[list | None] = mapped_column(JSONB, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class TraceEvent(Base):
    __tablename__ = "trace_events"
    # 全库唯一自增主键特例：留痕为高频批量写入，顺序自增比 UUID 更省索引与页分裂
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    type: Mapped[str] = mapped_column(String(16))  # route/llm/tool/memory/hitl
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class HitlTask(Base):
    __tablename__ = "hitl_tasks"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    trace_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    node_id: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    context: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/approved/rejected
    approver_id: Mapped[str | None] = mapped_column(String(36), index=True)  # 逻辑外键
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
