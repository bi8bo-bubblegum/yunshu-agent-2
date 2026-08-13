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
    status: Mapped[str] = mapped_column(String(16), default="running")  # running/completed/interrupted/failed/aborted
    supervisor_routes: Mapped[list | None] = mapped_column(JSONB, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class TraceEvent(Base):
    __tablename__ = "trace_events"
    # 全库唯一自增主键特例：留痕为高频批量写入，顺序自增比 UUID 更省索引与页分裂
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(36), index=True)  # 逻辑外键
    type: Mapped[str] = mapped_column(String(16))  # route/llm/tool/memory/approval
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Approval(Base):
    """统一审批中心。合并原 HitlTask + ExperienceApproval。
    - high 风险工具调用：interrupt 即时确认，不进审批中心（不创建本表记录）
    - critical 风险工具调用：创建本表记录，interrupt 冻结图等管理者审批
    - 经验晋升：创建本表记录，不阻塞图，等管理者审批"""
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    category: Mapped[str] = mapped_column(String(32), index=True)  # tool_call / experience_promotion
    risk: Mapped[str | None] = mapped_column(String(16))           # high / critical（仅 tool_call 有值）
    mode: Mapped[str] = mapped_column(String(16))                  # sync（阻塞图）/ async（不阻塞）
    ref_type: Mapped[str] = mapped_column(String(32))              # trace / experience
    ref_id: Mapped[str] = mapped_column(String(36), index=True)    # 关联对象 ID
    title: Mapped[str] = mapped_column(String(200))
    context: Mapped[dict | None] = mapped_column(JSONB)            # 工具参数 / 经验摘要
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/approved/rejected
    requester_id: Mapped[str] = mapped_column(String(36), index=True)   # 发起人
    approver_id: Mapped[str | None] = mapped_column(String(36), index=True)  # 审批人
    approver_role: Mapped[str | None] = mapped_column(String(32))  # 要求的审批角色（admin/dept_owner）
    comment: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    form_values: Mapped[dict | None] = mapped_column(JSONB)  # 用户填写的表单值（前端提交时的 fieldId→value 映射）
