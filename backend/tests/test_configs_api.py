# backend/tests/test_configs_api.py
"""任务 38：MCP 服务配置 API 集成测试。"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_mcp_config_crud():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "leah", "password": "x123456", "display_name": "Leah"})
        r = await c.post("/api/auth/login", json={"username": "leah", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/mcp-servers", json={"name": "erp", "url": "http://x/mcp"}, headers=h)
        assert r.status_code == 200
        r = await c.get("/api/mcp-servers", headers=h)
        assert any(m["name"] == "erp" for m in r.json())