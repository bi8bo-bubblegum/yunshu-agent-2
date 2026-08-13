# backend/app/api/dingtalk.py —— 钉钉对接路由（M3 组织同步 / M2 登录共用入口）
from functools import lru_cache
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import get_db, get_current_user
from app.models import DingTalkSyncState, User
from app.services.dingtalk.client import DingTalkError, dingtalk_client
from app.services.dingtalk.org_sync import OrgSyncService

router = APIRouter(tags=["dingtalk"])


@router.get("/api/dingtalk/status")
async def dingtalk_status(db: AsyncSession = Depends(get_db),
                          _: User = Depends(get_current_user)):
    """钉钉对接状态：是否启用 + 最近全量同步时间 + 审批模板清单（前端审批中心展示用）。"""
    last_sync = (await db.scalars(
        select(DingTalkSyncState).where(DingTalkSyncState.sync_type == "full_sync"))).first()
    return {
        "enabled": settings.dingtalk_enabled,
        "stream_enabled": settings.DINGTALK_STREAM_ENABLED,
        "corp_id": settings.DINGTALK_CORP_ID or None,
        "last_synced_at": last_sync.last_synced_at if last_sync else None,
        "process_codes": dict(settings.DINGTALK_OA_PROCESS_CODES),
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


@router.get("/api/dingtalk/form-schemas/{process_code}")
async def dingtalk_form_schema(process_code: str,
                                db: AsyncSession = Depends(get_db),
                                user: User = Depends(get_current_user)):
    """获取钉钉审批模板 schema，供前端动态渲染表单。

    process_code 必须在 DINGTALK_OA_PROCESS_CODES 取值范围内，防止越权读取未配置的模板。
    缓存结果 10 分钟 TTL，避免频繁调用钉钉接口。
    """
    # 校验 process_code 在已配置范围内
    configured = dict(settings.DINGTALK_OA_PROCESS_CODES)
    if process_code not in configured.values():
        raise HTTPException(status_code=404, detail="审批模板不存在或未配置（processCode 未匹配任何类目）")
    # 查找 category（用于日志）
    category = next((k for k, v in configured.items() if v == process_code), process_code)
    try:
        schema = await _get_cached_form_schema(process_code)
    except DingTalkError as e:
        if e.code in ("needAuth", "accessdenieddetail"):
            raise HTTPException(status_code=403, detail=f"缺少 Workflow.Form.Read 权限，请在钉钉开放平台申请：{e.message}")
        raise HTTPException(status_code=404, detail=f"获取模板 schema 失败：{e.message}")
    return {
        "process_code": process_code,
        "category": category,
        "schema": schema,
    }


# 内存缓存：process_code → schema 结果，TTL 10 分钟
_schema_cache: dict[str, dict] = {}
_schema_cache_time: dict[str, float] = {}
_SCHEMA_CACHE_TTL = 600  # 10 分钟


async def _get_cached_form_schema(process_code: str) -> dict:
    """缓存版获取模板 schema（10 分钟 TTL），避免频繁调用钉钉接口。"""
    import time
    cached = _schema_cache.get(process_code)
    if cached and _schema_cache_time.get(process_code, 0) < time.time() - _SCHEMA_CACHE_TTL:
        return cached
    schema = await dingtalk_client.get_form_schema(process_code)
    _schema_cache[process_code] = schema
    _schema_cache_time[process_code] = time.time()
    return schema
