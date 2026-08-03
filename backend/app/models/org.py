from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, String, func, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
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
    owner: Mapped["User | None"] = relationship(foreign_keys="Department.owner_id")
    users: Mapped[list["User"]] = relationship(back_populates="department", foreign_keys="User.department_id")

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    department_id: Mapped[str | None] = mapped_column(String(36), index=True)
    role_id: Mapped[str | None] = mapped_column(String(36), index=True)
    display_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    department: Mapped[Department | None] = relationship(back_populates="users",foreign_keys=[department_id])
    role: Mapped[Role | None] = relationship(foreign_keys=[role_id])