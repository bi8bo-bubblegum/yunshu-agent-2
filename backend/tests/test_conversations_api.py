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
