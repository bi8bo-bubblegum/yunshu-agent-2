# backend/tests/test_mcp_tool_timeout.py
"""MCP 工具执行超时保护单元测试。

外部 MCP 网关（天气/地图等第三方服务）无响应时，工具调用会无限挂起：SSE 流不结束、
前端一直转圈、trace 保持 running（真实事故：营销 agent 调 mcp_map 天气工具挂起 >5min）。
loader._with_exec_timeout 给 MCP 工具执行包 asyncio.wait_for，超时抛 TimeoutError →
ToolNode 记为工具错误，agent 继续而非挂死。"""
import asyncio

import pytest

from app.tools.loader import _with_exec_timeout


@pytest.mark.asyncio
async def test_async_tool_hanging_times_out():
    """async 工具外部网关挂起：超时后抛 asyncio.TimeoutError，不无限等待。"""
    async def hang(**kwargs):
        await asyncio.sleep(999)

    wrapped = _with_exec_timeout(hang, timeout=0.05)
    with pytest.raises(asyncio.TimeoutError):
        await wrapped()


@pytest.mark.asyncio
async def test_async_tool_normal_returns_result():
    """async 工具正常返回：透传结果，不被超时误杀。"""
    async def ok(**kwargs):
        return {"weather": "晴"}

    wrapped = _with_exec_timeout(ok, timeout=1.0)
    assert await wrapped() == {"weather": "晴"}


@pytest.mark.asyncio
async def test_sync_tool_passthrough():
    """sync 工具直接调用，不包 wait_for。"""
    def sync_fn(**kwargs):
        return {"ok": True}

    wrapped = _with_exec_timeout(sync_fn, timeout=1.0)
    assert await wrapped() == {"ok": True}
