# backend/app/services/approval_service.py
from datetime import datetime, timezone
from fastapi import HTTPException
from app.models.trace import Approval
from app.repositories.trace_repo import ApprovalRepository, TraceRepository
from app.repositories.experience_repo import ExperienceRepository


class ApprovalService:
    """统一审批中心：列出待办 + decide 按 category 分发后处理。
    - tool_call + sync（critical 工具调用）：更新审批单状态 + 恢复图执行
    - experience_promotion（经验晋升）：更新审批单状态 + 经验层级晋升"""
    def __init__(self, db):
        self.approval_repo = ApprovalRepository(db)
        self.trace_repo = TraceRepository(db)
        self.experience_repo = ExperienceRepository(db)

    async def list_pending(self, category: str | None = None):
        rows = await self.approval_repo.list_pending(category)
        return [{"id": a.id, "category": a.category, "risk": a.risk, "mode": a.mode,
                 "title": a.title, "context": a.context, "requester_id": a.requester_id,
                 "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None} for a in rows]

    async def create_approval(self, category: str, risk: str | None, mode: str,
                              ref_type: str, ref_id: str, title: str,
                              context: dict | None, requester_id: str,
                              approver_role: str | None = None) -> str:
        """创建审批单，返回审批单 ID。供 facade.guarded_critical 和 ExperienceService.submit 调用。"""
        approval = Approval(
            category=category, risk=risk, mode=mode,
            ref_type=ref_type, ref_id=ref_id, title=title,
            context=context, status="pending", requester_id=requester_id,
            approver_role=approver_role,
        )
        await self.approval_repo.add(approval)
        await self.approval_repo.commit()
        return approval.id

    async def decide(self, approval_id: str, approver_id: str, approve: bool, comment: str = ""):
        ap = await self.approval_repo.get(approval_id)
        if not ap or ap.status != "pending":
            raise HTTPException(404, "审批单不存在或已处理")

        # 1. 更新审批单（公共逻辑）
        ap.status = "approved" if approve else "rejected"
        ap.approver_id = approver_id
        ap.comment = comment
        ap.decided_at = datetime.now(timezone.utc)
        await self.approval_repo.commit()

        # 2. 按 category 分发后处理
        if ap.category == "tool_call" and ap.mode == "sync":
            # critical 工具调用：恢复 LangGraph 图执行
            await self._resume_graph(ap.id, approve, ap.ref_id)
        elif ap.category == "experience_promotion":
            # 经验晋升：通过则层级晋升
            if approve:
                await self._promote_experience(ap.ref_id, ap.context.get("to_scope", "dept"))
        return {"ok": True}

    async def _resume_graph(self, approval_id: str, approved: bool, trace_id: str):
        """审批通过/驳回后恢复图执行。"""
        from app.agents.graph import get_graph
        from langgraph.types import Command
        trace = await self.trace_repo.get(trace_id)
        if trace and trace.conversation_id:
            config = {"configurable": {"thread_id": trace.conversation_id}}
            graph = await get_graph()
            await graph.ainvoke(
                Command(resume={"approved": approved, "approval_id": approval_id}),
                config=config,
            )

    async def _promote_experience(self, experience_id: str, to_scope: str):
        """经验层级晋升。"""
        exp = await self.experience_repo.get(experience_id)
        if exp:
            exp.scope = to_scope
            exp.status = "approved"
            await self.experience_repo.commit()