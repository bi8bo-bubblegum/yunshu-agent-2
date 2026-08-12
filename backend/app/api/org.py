# backend/app/api/org.py —— 薄路由
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.schemas.auth import UserOut
from app.schemas.org import DepartmentCreate, DepartmentOut, UserUpdate
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

@router.patch("/api/users/{user_id}", response_model=UserOut)
async def update_user(user_id: str, body: UserUpdate, svc: OrgService = Depends(get_org_service),
                      user: User = Depends(get_current_user)):
    """分配用户的角色与部门：仅 admin 可操作（角色/部门归属影响审批与资源可见范围）。"""
    if (user.role_code or "") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可分配角色与部门")
    return await svc.update_user(user_id, body)