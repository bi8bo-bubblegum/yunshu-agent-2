# backend/app/api/org.py —— 薄路由
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.schemas.auth import UserOut
from app.schemas.org import DepartmentCreate, DepartmentOut
from app.services.org_service import OrgService

router = APIRouter(tags=["org"])

def get_org_service(db: AsyncSession = Depends(get_db)) -> OrgService:
    return OrgService(db)

@router.post("/api/departments", response_model=DepartmentOut)
async def create_department(body: DepartmentCreate, svc: OrgService = Depends(get_org_service), _: User = Depends(get_current_user)):
    return await svc.create_department(body.name)

@router.get("/api/departments", response_model=list[DepartmentOut])
async def list_departments(svc: OrgService = Depends(get_org_service), _: User = Depends(get_current_user)):
    return await svc.list_departments()

@router.get("/api/users", response_model=list[UserOut])
async def list_users(svc: OrgService = Depends(get_org_service), _: User = Depends(get_current_user)):
    return await svc.list_users()