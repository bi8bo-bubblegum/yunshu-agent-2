# backend/tests/test_org_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_department_crud():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "root", "password": "x123456", "display_name": "Root"})
        r = await c.post("/api/auth/login", json={"username": "root", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/departments", json={"name": "市场部"}, headers=h)
        assert r.status_code == 200
        dept_id = r.json()["id"]
        r = await c.get("/api/departments", headers=h)
        assert any(d["id"] == dept_id for d in r.json())


async def _register(transport, username, display_name="U"):
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": username, "password": "x123456", "display_name": display_name})
        r = await c.post("/api/auth/login", json={"username": username, "password": "x123456"})
        return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _set_admin(db_session, username):
    from sqlalchemy import update
    from app.models.org import User
    await db_session.execute(update(User).where(User.username == username).values(role_code="admin"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_admin_assigns_role_and_dept(db_session):
    """admin 给用户分配角色与部门；PATCH 缺省字段不修改。"""
    transport = ASGITransport(app=app)
    h_admin = await _register(transport, "mgr")
    await _set_admin(db_session, "mgr")
    h_user = await _register(transport, "alice")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        dept_id = (await c.post("/api/departments", json={"name": "市场部"}, headers=h_admin)).json()["id"]
        user_id = (await c.get("/api/users", headers=h_admin)).json()[-1]["id"]
        # 分配角色 + 部门
        r = await c.patch(f"/api/users/{user_id}", json={"role_code": "dept_owner", "department_id": dept_id},
                          headers=h_admin)
        assert r.status_code == 200, r.text
        assert r.json()["role_code"] == "dept_owner"
        assert r.json()["department_id"] == dept_id
        # 只改角色（department_id 缺省）→ 部门不变
        r = await c.patch(f"/api/users/{user_id}", json={"role_code": "member"}, headers=h_admin)
        assert r.status_code == 200
        assert r.json()["role_code"] == "member"
        assert r.json()["department_id"] == dept_id
        # 显式 null 清空部门
        r = await c.patch(f"/api/users/{user_id}", json={"department_id": None}, headers=h_admin)
        assert r.json()["department_id"] is None


@pytest.mark.asyncio
async def test_assign_forbidden_for_non_admin():
    """非 admin 调用分配接口 → 403。"""
    transport = ASGITransport(app=app)
    h = await _register(transport, "peon")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.patch("/api/users/some-id", json={"role_code": "admin"}, headers=h)
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_assign_validates_role_and_dept(db_session):
    """非法角色/部门 → 400；用户不存在 → 404。"""
    transport = ASGITransport(app=app)
    h_admin = await _register(transport, "mgr2")
    await _set_admin(db_session, "mgr2")
    h_user = await _register(transport, "bob")
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        user_id = (await c.get("/api/users", headers=h_admin)).json()[-1]["id"]
        # 非法角色
        r = await c.patch(f"/api/users/{user_id}", json={"role_code": "boss"}, headers=h_admin)
        assert r.status_code == 400
        # 不存在的部门
        r = await c.patch(f"/api/users/{user_id}", json={"department_id": "no-such-dept"}, headers=h_admin)
        assert r.status_code == 400
        # 用户不存在
        r = await c.patch("/api/users/no-such-user", json={"role_code": "member"}, headers=h_admin)
        assert r.status_code == 404
