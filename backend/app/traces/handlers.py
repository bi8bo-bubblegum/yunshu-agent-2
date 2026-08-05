# backend/app/traces/handlers.py
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
