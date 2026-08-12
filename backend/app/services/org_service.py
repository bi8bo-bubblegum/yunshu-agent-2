from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Department, User
from app.repositories.department_repo import DepartmentRepository
from app.repositories.user_repo import UserRepository
from app.schemas.org import UserUpdate

# 系统角色：与 seed.py ROLES 保持一致（member/dept_owner/admin）
ROLE_CODES = {"member", "dept_owner", "admin"}


def _valid_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


class OrgService:
    def __init__(self, db: AsyncSession):
        self.dept_repo = DepartmentRepository(db)
        self.user_repo = UserRepository(db)

    async def create_department(self, name: str) -> Department:
        if await self.dept_repo.get_by(name=name):
            raise HTTPException(status_code=409, detail=f"部门「{name}」已存在")
        dept = Department(name=name)
        await self.dept_repo.add(dept)
        await self.dept_repo.commit()
        return dept

    async def list_departments(self) -> list[Department]:
        return await self.dept_repo.list()

    async def list_users(self) -> list[User]:
        return await self.user_repo.list()

    async def update_user(self, user_id: str, body: UserUpdate) -> User:
        """分配用户的角色与部门（仅 admin 调用，PATCH 语义：缺省字段不修改）。
        校验角色 code 与部门 id 存在，避免逻辑外键指向不存在的数据（无 FK 约束，
        手动写错不会报错，这里在写入口拦截）。"""
        # 非 UUID 字符串直接绑定 UUID 列会触发 asyncpg 错误，先格式校验再查库
        if not _valid_uuid(user_id):
            raise HTTPException(status_code=404, detail="用户不存在")
        target = await self.user_repo.get(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="用户不存在")
        fields = body.model_fields_set
        if "role_code" in fields:
            if body.role_code is not None and body.role_code not in ROLE_CODES:
                raise HTTPException(status_code=400, detail=f"角色 {body.role_code} 不存在")
            target.role_code = body.role_code
        if "department_id" in fields:
            if body.department_id and (not _valid_uuid(body.department_id)
                                       or not await self.dept_repo.get(body.department_id)):
                raise HTTPException(status_code=400, detail="部门不存在")
            target.department_id = body.department_id
        await self.user_repo.commit()
        return target

