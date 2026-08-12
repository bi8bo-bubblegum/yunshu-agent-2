# backend/app/models/dingtalk.py
"""钉钉对接新增表：组织同步游标 + 审批实例绑定。"""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, DateTime, String, func, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class DingTalkSyncState(Base):
    """组织同步游标/时间戳：记录最近全量同步时间，用于定时兜底对账判定。"""
    __tablename__ = "dingtalk_sync_state"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    sync_type: Mapped[str] = mapped_column(String(32), unique=True)  # full_sync 等同步维度
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[str | None] = mapped_column(String(128))  # 分页游标（如需断点续传）


class ApprovalBinding(Base):
    """本地审批单与钉钉审批实例的绑定关系（M4 审批对接使用）。"""
    __tablename__ = "approval_binding"

    approval_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)  # 本地审批单 ID
    process_code: Mapped[str] = mapped_column(String(64))  # 钉钉审批模板编码
    process_instance_id: Mapped[str] = mapped_column(String(64), unique=True)  # 钉钉审批实例 ID
    pushed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), default="pushed", server_default="pushed")  # pushed/synced/revoked
