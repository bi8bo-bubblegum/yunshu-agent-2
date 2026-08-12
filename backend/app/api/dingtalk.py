# backend/app/api/dingtalk.py —— 钉钉对接路由（M3 组织同步 / M2 登录共用入口）
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_db, get_current_user
from app.models import DingTalkSyncState, User
from app.services.dingtalk.org_sync import OrgSyncService

router = APIRouter(tags=["dingtalk"])


@router.get("/api/dingtalk/status")
async def dingtalk_status(db: AsyncSession = Depends(get_db),
                          _: User = Depends(get_current_user)):
    """钉钉对接状态：是否启用 + 最近全量同步时间（前端组织管理页展示用）。"""
    last_sync = (await db.scalars(
        select(DingTalkSyncState).where(DingTalkSyncState.sync_type == "full_sync"))).first()
    return {
        "enabled": settings.dingtalk_enabled,
        "stream_enabled": settings.DINGTALK_STREAM_ENABLED,
        "corp_id": settings.DINGTALK_CORP_ID or None,
        "last_synced_at": last_sync.last_synced_at if last_sync else None,
    }


@router.post("/api/dingtalk/sync")
async def dingtalk_sync(db: AsyncSession = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """手动触发钉钉组织全量同步（仅 admin，幂等）。"""
    if (user.role_code or "") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可触发组织同步")
    if not settings.dingtalk_enabled:
        raise HTTPException(status_code=400, detail="钉钉应用未配置，无法同步组织")
    return await OrgSyncService(db).sync_all()
