# backend/tests/test_mcp_tool_risk.py
"""任务 38.6：MCP 工具风险等级配置单元测试。"""
import pytest
from app.tools.risk import get_mcp_risk


def test_get_mcp_risk_tool_level_overrides_default():
    """工具级覆盖优先于服务级默认。"""
    config = {"tool_risks": {"delete_order": "critical"}}
    assert get_mcp_risk("delete_order", "medium", config) == "critical"


def test_get_mcp_risk_falls_back_to_server_default():
    """无工具级覆盖时回退到服务级 default_risk。"""
    assert get_mcp_risk("query_order", "high", {}) == "high"


def test_get_mcp_risk_falls_back_to_medium():
    """服务级默认为空时兜底 medium。"""
    assert get_mcp_risk("query_order", "", {}) == "medium"
    assert get_mcp_risk("query_order", None, None) == "medium"


@pytest.mark.asyncio
async def test_update_tool_risks_api():
    """通过 API 更新 MCP 服务的工具风险配置。"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "riskuser", "password": "x123456", "display_name": "Risk"})
        r = await c.post("/api/auth/login", json={"username": "riskuser", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        # 先注册一个 MCP 服务
        await c.post("/api/mcp-servers", json={"name": "erp", "url": "http://localhost:8001/mcp"}, headers=h)
        # 更新工具风险
        r = await c.put("/api/mcp-servers/erp/tool-risks", json={
            "tool_risks": {"delete_order": "critical", "adjust_schedule": "high"}
        }, headers=h)
        assert r.status_code == 200
        assert r.json()["tool_risks"]["delete_order"] == "critical"