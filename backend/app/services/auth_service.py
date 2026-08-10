import asyncio

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
        # bcrypt 是同步 CPU 密集操作（cost≈12 单次约 0.3~0.5s）：直接跑在 async 事件循环
        # 会串行阻塞所有并发请求（真实事故：15 个并发登录全部延迟 7.5s）。
        # to_thread 移出事件循环，避免阻塞其他请求的 SSE 流式响应。
        password_hash = await asyncio.to_thread(hash_password, password)
        user = User(username=username, password_hash=password_hash, display_name=display_name)
        await self.user_repo.add(user)
        await self.user_repo.commit()
        return user

    async def login(self, username: str, password: str) -> str:
        user = await self.user_repo.get_by_username(username)
        ok = await asyncio.to_thread(verify_password, password, user.password_hash) if user else False
        if not ok:
            raise HTTPException(status_code=400, detail="用户名或密码错误")
        return create_access_token(user.id, user.username)
