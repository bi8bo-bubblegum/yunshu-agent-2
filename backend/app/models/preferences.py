# backend/app/models/preferences.py
from datetime import datetime
from uuid import uuid4
from sqlalchemy import UUID, DateTime, Float, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Preference(Base):
    __tablename__ = "preferences"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    category: Mapped[str] = mapped_column(String(16))  # style/decision/habit
    content: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 最近一次确认/刷新的时间，驱动注入排序（新鲜优先）。onupdate 仅作 ORM 兜底，
    # merge 命中时显式赋值（confidence 相同时 SQLAlchemy 不生成 UPDATE，onupdate 不触发）。
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )