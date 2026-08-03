# backend/app/api/auth.py —— 薄路由：只校验参数、调 service
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/auth", tags=["auth"])

def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)

@router.post("/register", response_model=UserOut)
async def register(body: RegisterRequest, svc: AuthService = Depends(get_auth_service)):
    return await svc.register(body.username, body.password, body.display_name)

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, svc: AuthService = Depends(get_auth_service)):
    return TokenResponse(access_token=await svc.login(body.username, body.password))

@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user