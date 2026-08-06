# backend/app/repositories/trace_repo.py
from sqlalchemy import String, and_, cast, or_, select
from app.models.org import User
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

    async def list_for_user(self, user_id: str, role_code: str | None, department_id: str | None,
                            status: str | None = None, category: str | None = None) -> list[Approval]:
        """按可见性过滤审批单：
        - admin：全部
        - 其他：我发起的 OR 我审批过的 OR（dept_owner 可见本部门待审批的经验晋升）"""
        q = select(Approval)
        if status:
            q = q.where(Approval.status == status)
        if category:
            q = q.where(Approval.category == category)
        if role_code == "admin":
            return list((await self.db.scalars(q.order_by(Approval.submitted_at.desc()))).all())
        q = q.outerjoin(User, cast(User.id, String) == Approval.requester_id)
        conds = [Approval.requester_id == user_id, Approval.approver_id == user_id]
        if role_code == "dept_owner" and department_id:
            conds.append(and_(
                Approval.status == "pending",
                Approval.approver_role == "dept_owner",
                User.department_id == department_id,
            ))
        return list((await self.db.scalars(
            q.where(or_(*conds)).order_by(Approval.submitted_at.desc())
        )).all())
