# backend/app/api/approval.py —— 薄路由（M4 全走钉钉审批，本地 decide 下线，仅保留列表）
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.approval_service import ApprovalService

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

def get_approval_service(db: AsyncSession = Depends(get_db)) -> ApprovalService:
    return ApprovalService(db)

@router.get("")
async def list_approvals(
    status: str | None = Query(None),
    category: str | None = Query(None),
    svc: ApprovalService = Depends(get_approval_service),
    user: User = Depends(get_current_user),
):
    return await svc.list_pending(user, status, category)