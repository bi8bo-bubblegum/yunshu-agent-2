# backend/app/api/approval.py —— 审批路由（M4 全走钉钉审批：列表 + 手动发起 + 提交推送）
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_current_user, get_db
from app.models.org import User
from app.services.approval_service import ApprovalService
from pydantic import BaseModel, Field


router = APIRouter(prefix="/api/approvals", tags=["approvals"])


def get_approval_service(db: AsyncSession = Depends(get_db)) -> ApprovalService:
    return ApprovalService(db)


# ------------------------------------------------------------------
# 审批列表（保留原 GET）
# ------------------------------------------------------------------

@router.get("")
async def list_approvals(
    status: str | None = Query(None),
    category: str | None = Query(None),
    svc: ApprovalService = Depends(get_approval_service),
    user: User = Depends(get_current_user),
):
    return await svc.list_pending(user, status, category)


# ------------------------------------------------------------------
# 手动发起审批（POST /initiate）
# ------------------------------------------------------------------

class InitiateRequest(BaseModel):
    """手动发起审批请求。"""
    category: str = Field(..., description="审批类目，必须在 DINGTALK_OA_PROCESS_CODES 中有值")
    title: str = Field(..., min_length=1, max_length=200, description="审批标题")
    context: dict | None = Field(None, description="上下文参数（可选，与 form_values 二选一）")
    form_values: dict = Field(default_factory=dict, description="用户填写的表单值 {fieldId: value}")


@router.post("/initiate")
async def initiate_approval(
    body: InitiateRequest,
    svc: ApprovalService = Depends(get_approval_service),
    user: User = Depends(get_current_user),
):
    """手动发起审批：仅创建 pending 单，不推送钉钉。

    用户填写表单后调用此接口创建审批单，然后通过 /{id}/submit 确认推送到钉钉。
    """
    # 校验 category 在已配置的 process_codes 中有值
    configured = dict(settings.DINGTALK_OA_PROCESS_CODES)
    if body.category not in configured:
        raise HTTPException(status_code=400, detail=f"审批类目「{body.category}」未配置（DINGTALK_OA_PROCESS_CODES），无法发起审批")
    approval = await svc.create_approval(
        category=body.category,
        risk=None,  # 手动审批无风险等级
        mode="async",  # 手动审批不阻塞图执行
        ref_type="manual",  # 手动审批标记
        ref_id="",  # 无关联 trace/experience
        title=body.title,
        context=body.context,
        requester_id=user.id,
        approver_role=None,  # 手动审批由钉钉模板决定审批流
        push_dingtalk=False,  # 不自动推送
        form_values=body.form_values if body.form_values else None,
    )
    return {
        "id": approval,
        "category": body.category,
        "title": body.title,
        "status": "pending",
        "form_values": body.form_values,
    }


# ------------------------------------------------------------------
# 确认提交审批到钉钉（POST /{id}/submit）
# ------------------------------------------------------------------

class SubmitRequest(BaseModel):
    """提交审批到钉钉请求。"""
    form_values: dict | None = None  # 表单值覆盖（审批中心弹窗填写时传，critical/晋升时不传）


@router.post("/{approval_id}/submit")
async def submit_approval(
    approval_id: str,
    body: SubmitRequest = SubmitRequest(),
    svc: ApprovalService = Depends(get_approval_service),
    user: User = Depends(get_current_user),
):
    """确认提交审批到钉钉。

    校验：审批单状态=pending + 当前用户是发起人 → 推送钉钉。
    form_values_override：弹窗填写的表单值（可选，不传则使用审批单已存的 form_values）。
    """
    binding = await svc.submit_to_dingtalk(
        approval_id=approval_id,
        form_values_override=body.form_values,
        current_user_id=user.id,
    )
    return {
        "approval_id": approval_id,
        "process_instance_id": binding.process_instance_id,
        "push_status": binding.status,
        "message": "审批已提交钉钉，等待审批",
    }
