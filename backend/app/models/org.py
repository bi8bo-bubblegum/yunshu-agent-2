from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint, func, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Role(Base):
    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))

class Department(Base):
    __tablename__ = "departments"
    # 钉钉允许不同父部门下同名部门，name 不再全局唯一，改为 (parent_id, name) 组合唯一
    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_departments_parent_name"),
        UniqueConstraint("dingtalk_dept_id", name="uq_departments_dingtalk_dept_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128))
    parent_id: Mapped[str | None] = mapped_column(String(36), index=True)  # 父部门（本地自引用），根部门为 NULL
    owner_id: Mapped[str | None] = mapped_column(String(36), index=True)
    # 钉钉同步字段
    dingtalk_dept_id: Mapped[int | None] = mapped_column(BigInteger)  # 钉钉部门 ID（根部门为 1）
    source: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")  # dingtalk/manual
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    department_id: Mapped[str | None] = mapped_column(String(36), index=True)
    role_code: Mapped[str | None] = mapped_column(String(32), index=True)  # 逻辑外键，关联 Role.code
    display_name: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 钉钉同步字段
    dingtalk_userid: Mapped[str | None] = mapped_column(String(64), unique=True)  # 钉钉员工唯一标识；本地手工账号为 NULL
    mobile: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(128))
    avatar: Mapped[str | None] = mapped_column(String(256))
    job_number: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")  # active/inactive（离职软删除）
    source: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")  # dingtalk/manual
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
