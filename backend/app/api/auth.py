# backend/app/api/auth.py —— 薄路由：只校验参数、调 service
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.schemas.auth import RegisterRequest, LoginRequest, DingTalkLoginRequest, TokenResponse, UserOut
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

@router.post("/dingtalk", response_model=TokenResponse)
async def dingtalk_login(body: DingTalkLoginRequest, svc: AuthService = Depends(get_auth_service)):
    """钉钉登录：workbench（工作台免登码）或 scan（网页扫码 authCode）。"""
    return TokenResponse(access_token=await svc.login_with_dingtalk(body.mode, body.code))


@router.get("/dingtalk/config")
async def dingtalk_config():
    """钉钉扫码登录配置（公开，无鉴权）：前端登录页跳转 login.dingtalk.com/oauth2/auth 需要。
    只暴露 client_id（AppKey）等非机密信息，绝不返回 client_secret。"""
    return {
        "enabled": settings.dingtalk_enabled,
        "client_id": settings.DINGTALK_CLIENT_ID or None,
    }

@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
