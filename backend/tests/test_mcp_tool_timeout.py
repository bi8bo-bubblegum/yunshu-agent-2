# backend/tests/test_mcp_tool_timeout.py
"""MCP 工具执行超时保护单元测试。

外部 MCP 网关（天气/地图等第三方服务）无响应时，工具调用会无限挂起：SSE 流不结束、
前端一直转圈、trace 保持 running（真实事故：营销 agent 调 mcp_map 天气工具挂起 >5min）。
loader._with_exec_timeout 给 MCP 工具执行包 asyncio.wait_for，超时抛 TimeoutError →
ToolNode 记为工具错误，agent 继续而非挂死。"""
import asyncio
import json

import pytest

from app.tools.loader import _with_exec_timeout, _bound_tool_result, TOOL_RESULT_LIMIT


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


# ---------------------------------------------------------------------------
# 工具返回体积限制（防止全量数据进图 state/checkpoint）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_huge_structured_result_truncated_to_limit():
    """结构化工具返回超大（模拟 query_lines 25MB）：截断后 ≤ 限制且仍是合法 JSON。"""
    huge = {"lines": [{"line_name": f"线路{i}", "data": "x" * 5000} for i in range(2000)]}
    bounded = _bound_tool_result(huge)
    s = json.dumps(bounded, ensure_ascii=False)
    assert len(s) <= TOOL_RESULT_LIMIT + 200, len(s)
    # 结构骨架保留：键名仍在、数组有省略标记
    assert "lines" in s
    assert "项省略" in s or "…" in s


@pytest.mark.asyncio
async def test_large_string_result_truncated():
    """纯字符串工具返回超限：硬切到限制并带截断标记。"""
    bounded = _bound_tool_result("y" * (TOOL_RESULT_LIMIT + 5000))
    assert len(bounded) < TOOL_RESULT_LIMIT + 200
    assert "已截断" in bounded


@pytest.mark.asyncio
async def test_small_result_untouched():
    """小工具返回原样透传（结构不变、值不截断）。"""
    small = {"weather": "晴", "temp": 28}
    assert _bound_tool_result(small) == small


@pytest.mark.asyncio
async def test_wrapped_tool_result_bounded():
    """_with_exec_timeout 包装后返回结果已做体积限制。"""
    async def big(**kwargs):
        return {"rows": [{"id": i, "payload": "z" * 4000} for i in range(500)]}

    wrapped = _with_exec_timeout(big, timeout=1.0)
    result = await wrapped()
    s = json.dumps(result, ensure_ascii=False)
    assert len(s) <= TOOL_RESULT_LIMIT + 200
