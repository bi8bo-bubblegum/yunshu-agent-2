# backend/tests/test_mcp_auth.py
"""MCP 认证：api_key/bearer 凭证组装 Authorization header。"""
from app.tools.mcp_adapter import _build_connection


def test_none_auth_no_headers():
    conn = _build_connection({"url": "http://localhost:8001/mcp", "auth_type": "none", "config": {}})
    assert conn == {"url": "http://localhost:8001/mcp", "transport": "streamable_http"}
    assert "headers" not in conn


def test_api_key_headers():
    conn = _build_connection({
        "url": "http://localhost:8001/mcp", "auth_type": "api_key",
        "config": {"api_key": "sk-test-123"},
    })
    assert conn["headers"] == {"Authorization": "Bearer sk-test-123"}


def test_bearer_headers():
    conn = _build_connection({
        "url": "http://localhost:8001/mcp", "auth_type": "bearer",
        "config": {"api_key": "tok-abc"},
    })
    assert conn["headers"] == {"Authorization": "Bearer tok-abc"}


def test_api_key_missing_no_headers():
    """声明了 api_key 但凭证未配置：不传认证信息（连接将按匿名处理）。"""
    conn = _build_connection({"url": "http://localhost:8001/mcp", "auth_type": "api_key", "config": {}})
    assert "headers" not in conn