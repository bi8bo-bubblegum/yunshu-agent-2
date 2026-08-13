# backend/tests/test_dingtalk_auth.py
"""M2 钉钉登录：工作台免登（workbench）/ 网页扫码（scan）两条链路换票。"""
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient, MockTransport, Response

from app.api.auth import get_auth_service
from app.main import app
from app.models import User
from app.services.auth_service import AuthService
from app.services.dingtalk.client import DingTalkClient


def make_dingtalk_client(userid: str = "ding_user_a") -> DingTalkClient:
    """Mock 钉钉登录链路：免登/扫码（新版 OAuth2）/unionid 换 userid 全返回同一 userid。"""
    def handler(request):
        path = request.url.path
        if path == "/v1.0/oauth2/accessToken":
            return Response(200, json={"accessToken": "T", "expireIn": 7200})
        if path == "/topapi/v2/user/getuserinfo":
            return Response(200, json={"errcode": 0, "result": {"userid": userid, "unionid": "union_x"}})
        if path == "/v1.0/oauth2/userAccessToken":
            return Response(200, json={"accessToken": "USER_T", "expireIn": 7200})
        if path == "/v1.0/contact/users/me":
            return Response(200, json={"unionId": "union_x", "nick": "张三"})
        if path == "/topapi/user/getbyunionid":
            return Response(200, json={"errcode": 0, "result": {"userid": userid}})
        return Response(404, json={})
    return DingTalkClient(client_id="k", client_secret="s", transport=MockTransport(handler))


async def _add_synced_user(db_session, userid: str = "ding_user_a", status: str = "active") -> User:
    """预置一个本地已同步的钉钉用户（M3 组织同步产物）。"""
    user = User(username=userid, password_hash="!", display_name="张三",
                dingtalk_userid=userid, source="dingtalk", status=status)
    db_session.add(user)
    await db_session.commit()
    return user


# ---------------------------------------------------------------------------
# service 层：两条登录链路
# ---------------------------------------------------------------------------

async def test_workbench_login_success(db_session):
    """钉钉内工作台免登：免登码 → userid → 本地匹配 → 签发 JWT。"""
    await _add_synced_user(db_session)
    svc = AuthService(db_session, dt_client=make_dingtalk_client())
    token = await svc.login_with_dingtalk("workbench", "authcode_xxx")
    assert token and isinstance(token, str)


async def test_scan_login_success(db_session):
    """网页扫码：authCode → unionid → getbyunionid → userid → 本地匹配 → JWT。"""
    await _add_synced_user(db_session)
    svc = AuthService(db_session, dt_client=make_dingtalk_client())
    token = await svc.login_with_dingtalk("scan", "scan_code_xxx")
    assert token


async def test_scan_login_user_not_synced(db_session):
    """扫码拿到 userid 但本地未同步 → 403 提示。"""
    svc = AuthService(db_session, dt_client=make_dingtalk_client("nobody"))
    with pytest.raises(HTTPException) as ei:
        await svc.login_with_dingtalk("scan", "scan_code_xxx")
    assert ei.value.status_code == 403
    assert "未同步" in ei.value.detail


async def test_login_user_inactive_rejected(db_session):
    """本地账号已停用 → 403。"""
    await _add_synced_user(db_session, status="inactive")
    svc = AuthService(db_session, dt_client=make_dingtalk_client())
    with pytest.raises(HTTPException) as ei:
        await svc.login_with_dingtalk("workbench", "authcode_xxx")
    assert ei.value.status_code == 403


async def test_login_invalid_mode(db_session):
    """不支持的 mode → 400。"""
    svc = AuthService(db_session, dt_client=make_dingtalk_client())
    with pytest.raises(HTTPException) as ei:
        await svc.login_with_dingtalk("wechat", "x")
    assert ei.value.status_code == 400


# ---------------------------------------------------------------------------
# API 层：POST /api/auth/dingtalk
# ---------------------------------------------------------------------------

async def test_dingtalk_login_api(db_session):
    """路由返回 TokenResponse。"""
    await _add_synced_user(db_session)
    svc = AuthService(db_session, dt_client=make_dingtalk_client())
    app.dependency_overrides[get_auth_service] = lambda: svc
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/auth/dingtalk", json={"mode": "workbench", "code": "x"})
            assert resp.status_code == 200
            assert resp.json()["access_token"]
    finally:
        app.dependency_overrides.clear()
