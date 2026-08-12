import asyncio

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password, create_access_token
from app.models import User
from app.repositories.user_repo import UserRepository
from app.services.dingtalk.client import DingTalkClient, DingTalkError, dingtalk_client


class AuthService:
    def __init__(self, db: AsyncSession, dt_client: DingTalkClient | None = None):
        self.user_repo = UserRepository(db)
        # 可注入 MockTransport 客户端便于单测；默认用进程内单例
        self.dt_client = dt_client or dingtalk_client

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

    async def login_with_dingtalk(self, mode: str, code: str) -> str:
        """钉钉登录（M2，两条链路最终都得到钉钉 userid）：
        - workbench：钉钉内 H5 工作台免登码（dd.getAuthCode）→ userid+unionid
        - scan：网页端扫码回跳 authCode → unionid（sns 接口）→ userid（getbyunionid）
        再按 dingtalk_userid 匹配本地用户签发 JWT；未同步/已停用账号拒绝。
        """
        try:
            if mode == "workbench":
                info = await self.dt_client.get_userinfo_by_code(code)
                userid = info.get("userid")
            elif mode == "scan":
                user_info = await self.dt_client.get_sns_userinfo_bycode(code)
                unionid = user_info.get("unionid")
                userid = await self.dt_client.get_user_by_unionid(unionid) if unionid else None
            else:
                raise HTTPException(status_code=400, detail="不支持的钉钉登录方式")
        except DingTalkError as e:
            raise HTTPException(status_code=400, detail=f"钉钉登录失败：{e.message}")
        if not userid:
            raise HTTPException(status_code=400, detail="钉钉登录失败：未获取到用户信息")
        user = await self.user_repo.get_by(dingtalk_userid=userid)
        if not user:
            raise HTTPException(status_code=403,
                                detail="该钉钉账号未同步到系统，请联系管理员在组织管理页同步钉钉组织")
        if user.status == "inactive":
            raise HTTPException(status_code=403, detail="该账号已停用，无法登录")
        return create_access_token(user.id, user.username)
