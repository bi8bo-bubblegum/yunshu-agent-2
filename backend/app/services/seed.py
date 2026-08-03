# backend/app/services/seed.py —— 种子业务也只走 repo，不直查 DB
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.org import Role
from app.repositories.base import BaseRepository

class RoleRepository(BaseRepository):
    model = Role

ROLES = [("member", "成员"), ("dept_owner", "部门负责人"), ("admin", "公司管理员")]

async def seed_roles(db: AsyncSession) -> None:
    roles = RoleRepository(db)
    for code, name in ROLES:
        if not await roles.get_by(code=code):
            await roles.add(Role(code=code, name=name))