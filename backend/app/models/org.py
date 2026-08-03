from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, String, func, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))

class Department(Base):
    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), unique=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True)

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    department_id: Mapped[str | None] = mapped_column(String(36), index=True)
    role_code: Mapped[str | None] = mapped_column(String(32), index=True)  # 逻辑外键，关联 Role.code
    display_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
