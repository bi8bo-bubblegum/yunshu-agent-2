from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Department, User
from app.repositories.department_repo import DepartmentRepository
from app.repositories.user_repo import UserRepository


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

