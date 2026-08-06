# backend/tests/test_agent_mcp_binding.py
"""任务 38.5：Agent MCP 绑定动态化集成测试。"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_load_mcp_tools_by_agent(db_session):
    """从数据库读取 agent 的 MCP 绑定并加载 MCP 服务名列表。"""
    from app.tools.loader import load_mcp_tools_by_agent
    from app.services.seed import seed_agent_mcp_bindings
    await seed_agent_mcp_bindings(db_session)
    mcp_server_names = await load_mcp_tools_by_agent(db_session, "marketing")
    assert "erp" in mcp_server_names


@pytest.mark.asyncio
async def test_agent_mcp_binding_api():
    """通过 API 管理 agent MCP 绑定。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "admin1", "password": "x123456", "display_name": "Admin"})
        r = await c.post("/api/auth/login", json={"username": "admin1", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        # 查看默认绑定
        r = await c.get("/api/agents/marketing/mcp-bindings", headers=h)
        assert r.status_code == 200
        # 新增绑定
        r = await c.post("/api/agents/marketing/mcp-bindings", json={"mcp_server_name": "crm"}, headers=h)
        assert r.status_code == 200
        assert r.json()["mcp_server_name"] == "crm"
        # 移除
        binding_id = r.json()["id"]
        r = await c.delete(f"/api/agents/marketing/mcp-bindings/{binding_id}", headers=h)
        assert r.status_code == 200