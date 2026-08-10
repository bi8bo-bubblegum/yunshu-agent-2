# backend/tests/test_llm_stream.py —— stream_llm 流式生成超时降级
import asyncio

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from app.agents.llm_stream import stream_llm


class FakeStreamLLM:
    """正常流式 LLM：逐 chunk 产出（真实 ChatOpenAI.astream 产出 AIMessageChunk）。"""

    def __init__(self, contents):
        self._contents = contents

    async def astream(self, msgs):
        for c in self._contents:
            await asyncio.sleep(0.01)
            yield AIMessageChunk(content=c)


class HangingStreamLLM:
    """网关挂起模拟：产出部分 chunk 后不再响应（不发后续也不断连）。

    真实事故：resume 恢复图执行后 agent 二次生成挂起 >170s，前端永不返回。
    stream_llm 必须超时降级而非无限等待。
    """

    def __init__(self, contents_before_hang):
        self._contents = contents_before_hang

    async def astream(self, msgs):
        for c in self._contents:
            await asyncio.sleep(0.01)
            yield AIMessageChunk(content=c)
        await asyncio.sleep(30)  # 模拟网关在流中途挂起


class HangingEmptyStreamLLM:
    """网关完全无响应：一个 chunk 都不产出。"""

    async def astream(self, msgs):
        await asyncio.sleep(30)
        yield AIMessageChunk(content="")  # 不会执行到；使函数成为 async generator


@pytest.mark.asyncio
async def test_stream_llm_merges_chunks():
    """正常流式：全部 chunk 合并为完整文本（含 tool_calls 场景由 ReAct 继续）。"""
    llm = FakeStreamLLM(["营销方案第一部分", "，第二部分"])
    resp = await stream_llm(llm, [], timeout=5.0)
    assert isinstance(resp, AIMessage)
    assert resp.content == "营销方案第一部分，第二部分"


@pytest.mark.asyncio
async def test_stream_llm_timeout_keeps_collected():
    """流中途挂起：超时后返回已收集 chunk 合并结果，不抛异常、不无限阻塞。"""
    llm = HangingStreamLLM(["已生成的前半段内容"])
    resp = await stream_llm(llm, [], timeout=0.2)
    assert resp.content == "已生成的前半段内容"


@pytest.mark.asyncio
async def test_stream_llm_timeout_empty_fallback():
    """一个 chunk 都没收到（网关完全无响应）：返回降级提示消息，图不崩溃。"""
    llm = HangingEmptyStreamLLM()
    resp = await stream_llm(llm, [], timeout=0.2)
    assert isinstance(resp, AIMessage)
    assert "超时" in resp.content


@pytest.mark.asyncio
async def test_stream_llm_pushes_sse_tokens():
    """逐 chunk 文本实时推送到 sse_queue（前端逐 token 输出依赖）。"""
    q: asyncio.Queue = asyncio.Queue()
    llm = FakeStreamLLM(["a", "b", "c"])
    await stream_llm(llm, [], q, timeout=5.0)
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert [e["content"] for e in events] == ["a", "b", "c"]
    assert all(e["event"] == "token" for e in events)
