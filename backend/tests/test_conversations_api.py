# backend/tests/test_conversations_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_conversation_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "carol", "password": "x123456", "display_name": "Carol"})
        r = await c.post("/api/auth/login", json={"username": "carol", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/conversations", json={"title": "测试"}, headers=h)
        assert r.status_code == 200
        conv_id = r.json()["id"]
        r = await c.get(f"/api/conversations/{conv_id}/messages", headers=h)
        assert r.json() == []


@pytest.mark.asyncio
async def test_delete_conversation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "deleter", "password": "x123456", "display_name": "Deleter"})
        r = await c.post("/api/auth/login", json={"username": "deleter", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        await c.post("/api/auth/register", json={"username": "other", "password": "x123456", "display_name": "Other"})
        r = await c.post("/api/auth/login", json={"username": "other", "password": "x123456"})
        h_other = {"Authorization": f"Bearer {r.json()['access_token']}"}

        r = await c.post("/api/conversations", json={"title": "待删除"}, headers=h)
        conv_id = r.json()["id"]

        # 越权删除他人会话 → 404
        r = await c.delete(f"/api/conversations/{conv_id}", headers=h_other)
        assert r.status_code == 404

        # 删除后会话消失、消息清空、重复删除 404
        r = await c.delete(f"/api/conversations/{conv_id}", headers=h)
        assert r.status_code == 200
        r = await c.get("/api/conversations", headers=h)
        assert conv_id not in [x["id"] for x in r.json()]
        r = await c.delete(f"/api/conversations/{conv_id}", headers=h)
        assert r.status_code == 404
