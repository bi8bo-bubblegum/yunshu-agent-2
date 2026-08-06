# backend/tests/test_mcp_adapter.py
"""任务 37：MCP 注册表与动态工具发现单测。"""
from app.tools.mcp_adapter import MCPRegistry


def test_mcp_registry_empty_init():
    reg = MCPRegistry()
    assert reg.list() == []


def test_register_mcp_config():
    reg = MCPRegistry()
    reg.register({"name": "erp", "url": "http://localhost:8001/mcp", "enabled": True})
    assert "erp" in reg.list()