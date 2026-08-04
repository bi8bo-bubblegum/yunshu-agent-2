# backend/app/services/approval_service.py
from datetime import datetime, timezone
from fastapi import HTTPException
from app.repositories.experience_repo import ApprovalRepository, ExperienceRepository

class ApprovalService:
    """审批业务：列出待办 + 审批通过则晋升经验层级。"""
    def __init__(self, db):
        self.approval_repo = ApprovalRepository(db)
        self.experience_repo = ExperienceRepository(db)

    async def list_pending(self):
        rows = await self.approval_repo.list_pending()
        return [{"id": a.id, "experience_id": a.experience_id, "from_scope": a.from_scope, "to_scope": a.to_scope} for a in rows]

    async def decide(self, approval_id: str, approver_id: str, approve: bool, comment: str = ""):
        ap = await self.approval_repo.get(approval_id)
        if not ap or ap.status != "pending":
            raise HTTPException(404, "审批不存在")
        exp = await self.experience_repo.get(ap.experience_id)
        ap.status = "approved" if approve else "rejected"
        ap.approver_id = approver_id
        ap.comment = comment
        ap.decided_at = datetime.now(timezone.utc)
        if approve:
            exp.scope = ap.to_scope
            exp.status = "approved"
        else:
            exp.status = "rejected"
        await self.approval_repo.commit()  # 事务提交走 repository
        return {"ok": True}