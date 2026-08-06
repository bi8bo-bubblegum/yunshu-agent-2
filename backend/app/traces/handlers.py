# backend/app/traces/handlers.py
import asyncio

from langchain_core.callbacks import AsyncCallbackHandler

from app.traces.collector import collector


class TraceCallbackHandler(AsyncCallbackHandler):
    """LangChain/LangGraph 异步回调：把 LLM/Tool 事件写入留痕队列。"""

    def __init__(self, trace_id: str):
        self.trace_id = trace_id

    async def on_llm_start(self, serialized, prompts, **kwargs):
        collector.emit(self.trace_id, "llm_call", {"event": "start", "prompt": prompts[0][:2000]})

    async def on_llm_end(self, response, **kwargs):
        text = getattr(response, "text", "")[:2000]
        collector.emit(self.trace_id, "llm_call", {"event": "end", "output": text})

    async def on_tool_start(self, serialized, input_str, **kwargs):
        collector.emit(self.trace_id, "tool_call",
                       {"event": "start", "name": serialized.get("name"), "args": input_str[:2000]})

    async def on_tool_end(self, output, **kwargs):
        collector.emit(self.trace_id, "tool_call", {"event": "end", "output": str(output)[:2000]})


class StreamEventHandler(AsyncCallbackHandler):
    """流式过程事件处理器：把工具调用等中间过程实时推送到请求级队列（SSE 转发给前端），
    同时照常写入留痕。"""

    def __init__(self, queue: asyncio.Queue, trace_id: str):
        self.queue = queue
        self.trace_id = trace_id
        self._tool_runs: dict[str, str] = {}

    async def on_tool_start(self, serialized, input_str, **kwargs):
        name = serialized.get("name")
        self._tool_runs[kwargs.get("run_id", "")] = name
        collector.emit(self.trace_id, "tool_call",
                       {"event": "start", "name": name, "args": input_str[:2000]})
        await self._push({"event": "tool_start", "tool": name, "args": input_str[:2000]})

    async def on_tool_end(self, output, **kwargs):
        name = self._tool_runs.pop(kwargs.get("run_id", ""), "未知工具")
        collector.emit(self.trace_id, "tool_call",
                       {"event": "end", "name": name, "output": str(output)[:2000]})
        await self._push({"event": "tool_end", "tool": name, "result": str(output)[:2000]})

    async def _push(self, evt: dict) -> None:
        try:
            self.queue.put_nowait(evt)
        except asyncio.QueueFull:
            pass
