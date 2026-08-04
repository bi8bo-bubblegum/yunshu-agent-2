# backend/app/api/approvals.py —— 薄路由
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.approval_service import ApprovalService

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

class DecideRequest(BaseModel):
    approve: bool
    comment: str = ""

def get_approval_service(db: AsyncSession = Depends(get_db)) -> ApprovalService:
    return ApprovalService(db)

@router.get("")
async def list_approvals(
    status: str | None = Query(None),
    category: str | None = Query(None),
    svc: ApprovalService = Depends(get_approval_service),
    _: User = Depends(get_current_user),
):
    return await svc.list_pending(category)

@router.post("/{approval_id}/decide")
async def decide_approval(approval_id: str, body: DecideRequest, svc: ApprovalService = Depends(get_approval_service), user: User = Depends(get_current_user)):
    return await svc.decide(approval_id, user.id, body.approve, body.comment)