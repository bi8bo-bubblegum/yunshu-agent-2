# backend/app/api/experiences.py —— 薄路由
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.experience_service import ExperienceService
from app.services.experience_svc import upload_campaign_file

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


@router.post("/upload")
async def upload_experience_file(file: UploadFile = File(...), db: AsyncSession = Depends(get_db),
                                 user: User = Depends(get_current_user)):
    """上传营销活动文件（pdf/docx/txt/md），解析后自动沉淀为个人草稿经验。"""
    content = await file.read()
    exp = await upload_campaign_file(db, user.id, user.department_id, file.filename, content)
    return {"ok": True, "id": exp.id, "title": exp.title, "summary": exp.summary}


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


@router.get("/{exp_id}")
async def get_experience(exp_id: str, svc: ExperienceService = Depends(get_exp_service),
                         user: User = Depends(get_current_user)):
    """经验详情：返回全部内容字段，按可见范围校验（个人/部门/公司）。"""
    e = await svc.get_detail(user.id, exp_id, user.department_id)
    return {
        "id": e.id,
        "title": e.title,
        "summary": e.summary,
        "content": e.content,
        "tags": e.tags,
        "scope": e.scope,
        "status": e.status,
        "event_time": e.event_time.isoformat() if e.event_time else None,
        "result_metrics": e.result_metrics,
        "owner_id": e.owner_id,
        "created_at": e.created_at,
    }
