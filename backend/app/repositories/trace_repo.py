# backend/app/repositories/trace_repo.py
from sqlalchemy import select
from app.models.trace import ExecutionTrace, TraceEvent, Approval
from app.repositories.base import BaseRepository


class TraceRepository(BaseRepository[ExecutionTrace]):
    model = ExecutionTrace

    async def list_by_user(self, user_id: str, limit: int = 50) -> list[ExecutionTrace]:
        return list((await self.db.scalars(
            select(ExecutionTrace).where(ExecutionTrace.user_id == user_id)
            .order_by(ExecutionTrace.started_at.desc()).limit(limit)
        )).all())


class EventRepository(BaseRepository[TraceEvent]):
    model = TraceEvent

    async def list_by_trace(self, trace_id: str) -> list[TraceEvent]:
        return list((await self.db.scalars(
            select(TraceEvent).where(TraceEvent.trace_id == trace_id).order_by(TraceEvent.id)
        )).all())


class ApprovalRepository(BaseRepository[Approval]):
    """统一审批中心 Repository，替代原 HitlRepository + 经验 ApprovalRepository。"""
    model = Approval

    async def list_pending(self, category: str | None = None) -> list[Approval]:
        q = select(Approval).where(Approval.status == "pending")
        if category:
            q = q.where(Approval.category == category)
        return list((await self.db.scalars(q.order_by(Approval.submitted_at.desc()))).all())
