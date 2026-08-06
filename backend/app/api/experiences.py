# backend/app/api/experiences.py —— 薄路由
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.experience_service import ExperienceService

router = APIRouter(prefix="/api/experiences", tags=["experiences"])


class ExperienceCreate(BaseModel):
    title: str
    summary: str
    content: str = ""
    tags: list[str] = []
    event_time: str | None = None
    result_metrics: dict | None = None


class SubmitRequest(BaseModel):
    to_scope: str  # dept/company


def get_exp_service(db: AsyncSession = Depends(get_db)) -> ExperienceService:
    return ExperienceService(db)


@router.post("")
async def create_experience(body: ExperienceCreate, svc: ExperienceService = Depends(get_exp_service),
                            user: User = Depends(get_current_user)):
    return await svc.create(user.id, user.department_id, body)


@router.post("/{exp_id}/submit")
async def submit_experience(exp_id: str, body: SubmitRequest, svc: ExperienceService = Depends(get_exp_service),
                            user: User = Depends(get_current_user)):
    return await svc.submit(user.id, exp_id, body.to_scope)


@router.get("")
async def list_experiences(svc: ExperienceService = Depends(get_exp_service), user: User = Depends(get_current_user)):
    rows = await svc.list_visible(user.id, user.department_id)
    return [{"id": e.id, "title": e.title, "scope": e.scope, "status": e.status, "summary": e.summary} for e in rows]


@router.delete("/{exp_id}")
async def delete_experience(exp_id: str, svc: ExperienceService = Depends(get_exp_service),
                            user: User = Depends(get_current_user)):
    """删除经验（作者本人或 admin），用于清理重复/无效经验。"""
    await svc.delete(user.id, exp_id, user.role_code)
    return {"ok": True}
