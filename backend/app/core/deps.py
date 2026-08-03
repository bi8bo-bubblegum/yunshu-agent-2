from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models import User

bearer = HTTPBearer(auto_error=False)

async def get_db():
    async with SessionLocal() as db:
        yield db

async def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: AsyncSession = Depends(get_db)) -> User | None:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    try:
        payload = decode_token(creds.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token无效")
    user = await db.scalar(select(User).where(User.id == payload["sub"]))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user
