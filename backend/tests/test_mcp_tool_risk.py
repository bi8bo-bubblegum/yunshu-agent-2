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


async def _reg_and_login(c) -> dict:
    await c.post("/api/auth/register", json={"username": "riskuser", "password": "x123456", "display_name": "Risk"})
    r = await c.post("/api/auth/login", json={"username": "riskuser", "password": "x123456"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _fresh_config(db_session, server_name: str) -> dict:
    """用独立查询读取数据库真实 config，绕开 session identity map 缓存。"""
    from app.models.configs import McpServer
    from sqlalchemy import select
    row = (await db_session.execute(select(McpServer).where(McpServer.name == server_name))).scalar_one()
    return dict(row.config or {})


@pytest.mark.asyncio
async def test_update_tool_risks_api(db_session):
    """通过 API 更新 MCP 服务的工具风险配置，并验证真实持久化。"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _reg_and_login(c)
        # 先注册一个 MCP 服务
        await c.post("/api/mcp-servers", json={"name": "erp", "url": "http://localhost:8001/mcp"}, headers=h)
        # 更新工具风险
        r = await c.put("/api/mcp-servers/erp/tool-risks", json={
            "tool_risks": {"delete_order": "critical", "adjust_schedule": "high"}
        }, headers=h)
        assert r.status_code == 200
        assert r.json()["tool_risks"]["delete_order"] == "critical"
        # 关键断言：数据库真实落库（此前 JSONB 同引用赋值不触发 UPDATE，此处会失败）
        cfg = await _fresh_config(db_session, "erp")
        assert cfg["tool_risks"]["delete_order"] == "critical"
        assert cfg["tool_risks"]["adjust_schedule"] == "high"


@pytest.mark.asyncio
async def test_update_tool_risks_when_config_already_nonempty(db_session):
    """config 已有其他键（如 api_key）时更新风险仍须落库。
    回归：JSONB 原地修改 + 同引用赋值不触发 UPDATE 的 bug。"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _reg_and_login(c)
        # 先创建服务并写入认证（使 config 非空，逼近真实场景）
        await c.post("/api/mcp-servers", json={"name": "erp2", "url": "http://localhost:8001/mcp"}, headers=h)
        r = await c.put("/api/mcp-servers/erp2/auth", json={"auth_type": "bearer", "api_key": "sk-123"}, headers=h)
        assert r.status_code == 200
        cfg = await _fresh_config(db_session, "erp2")
        assert cfg.get("api_key") == "sk-123"
        # config 非空时更新工具风险
        r = await c.put("/api/mcp-servers/erp2/tool-risks", json={
            "tool_risks": {"delete_order": "critical"}
        }, headers=h)
        assert r.status_code == 200
        cfg = await _fresh_config(db_session, "erp2")
        # 回归断言：api_key 保留 + 新风险写入（修复前 tool_risks 丢失）
        assert cfg.get("api_key") == "sk-123"
        assert cfg["tool_risks"]["delete_order"] == "critical"


@pytest.mark.asyncio
async def test_update_mcp_auth_persists(db_session):
    """仅修改密钥（auth_type 不变）时 config 仍须落库。
    回归：与 tool_risks 同类的 JSONB 原地修改 bug。"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        h = await _reg_and_login(c)
        await c.post("/api/mcp-servers", json={"name": "erp3", "url": "http://localhost:8001/mcp"}, headers=h)
        # 初次配置 bearer 认证
        r = await c.put("/api/mcp-servers/erp3/auth", json={"auth_type": "bearer", "api_key": "old-key"}, headers=h)
        assert r.status_code == 200
        # 仅换密钥，auth_type 保持 bearer 不变
        r = await c.put("/api/mcp-servers/erp3/auth", json={"auth_type": "bearer", "api_key": "new-key"}, headers=h)
        assert r.status_code == 200
        cfg = await _fresh_config(db_session, "erp3")
        assert cfg.get("api_key") == "new-key"