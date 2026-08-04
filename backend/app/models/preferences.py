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