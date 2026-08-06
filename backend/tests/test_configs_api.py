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


@pytest.mark.asyncio
async def test_binding_change_invalidates_graph(monkeypatch):
    """Agent MCP 绑定增删后，主图缓存立即失效（下次对话懒重建，无需重启）。"""
    from app.agents import graph as graph_module
    from app.services.config_service import ConfigService
    from app.core.database import SessionLocal

    async with SessionLocal() as db:
        svc = ConfigService(db)
        await svc.add_agent_binding("marketing", "erp")
        assert graph_module._graph is None
        await svc.remove_agent_binding((await svc.list_agent_bindings("marketing"))[0].id)
        assert graph_module._graph is None
