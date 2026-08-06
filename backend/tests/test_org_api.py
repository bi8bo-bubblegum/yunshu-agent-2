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
