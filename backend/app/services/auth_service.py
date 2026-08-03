from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password, create_access_token
from app.models import User
from app.repositories.user_repo import UserRepository


class AuthService:
    def __init__(self, db: AsyncSession):
        self.user_repo = UserRepository(db)

    async def register(self, username: str, password: str, display_name: str) -> User:
        if await self.user_repo.get_by_username(username):
            raise HTTPException(status_code=400, detail="用户名已存在")
        user = User(username=username, password_hash=hash_password(password), display_name=display_name)
        await self.user_repo.add(user)
        return user

    async def login(self, username: str, password: str) -> str:
        user = await self.user_repo.get_by_username(username)
        if not user or not verify_password(password, user.password_hash):
            raise HTTPException(status_code=400, detail="用户名或密码错误")
        return create_access_token(user.id, user.username)
