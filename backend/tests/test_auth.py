# backend/tests/test_auth.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_register_and_login():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/api/auth/register", json={"username": "alice", "password": "pass123", "display_name": "Alice"})
        assert r.status_code == 200
        r = await client.post("/api/auth/login", json={"username": "alice", "password": "pass123"})
        assert r.status_code == 200 and "access_token" in r.json()
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
        assert me.json()["username"] == "alice"
