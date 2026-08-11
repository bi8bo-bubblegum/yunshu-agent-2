# backend/app/traces/handlers.py
import asyncio
import ast
import json

from langchain_core.callbacks import AsyncCallbackHandler

from app.traces.collector import collector

# ---- 结构化工具卡片：体积截断与工具调用收集 ----
_MAX_STR = 500        # 单字符串截断长度
_MAX_ITEMS = 20       # 单层 dict/list 最大条目数
_MAX_DEPTH = 3        # 最大嵌套深度


def _truncate_value(v, *, _depth: int = 0):
    """递归截断不可控体积的值（字符串/列表/dict），保持 JSON 可序列化。

    工具入参/结果可能非常大（整表查询结果、长文本），直接入库会撑爆 metadata。
    深度与条目都设上限，超出的部分折叠为占位说明，不丢失结构骨架。"""
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return v[:_MAX_STR]
    if isinstance(v, list):
        if _depth >= _MAX_DEPTH:
            return f"[{len(v)} 项]" if v else []
        out = [_truncate_value(x, _depth=_depth + 1) for x in v[:_MAX_ITEMS]]
        if len(v) > _MAX_ITEMS:
            out.append("…")
        return out
    if isinstance(v, dict):
        if _depth >= _MAX_DEPTH:
            return f"{{{len(v)} 字段}}"
        out = {}
        for k, val in list(v.items())[:_MAX_ITEMS]:
            out[str(k)] = _truncate_value(val, _depth=_depth + 1)
        if len(v) > _MAX_ITEMS:
            out["…"] = "…"
        return out
    return str(v)[:_MAX_STR]          # 非序列化兜底


def _tool_args(**kwargs):
    """结构化入参：优先用 langchain 过滤注入参数后的 inputs，回退解析 input_str。

    input_str 是 LangChain 序列化的字符串（可能是 Python repr 而非 JSON），
    用 kwargs['inputs']（结构化 dict）最可靠；缺失时依次尝试 JSON / ast 解析。"""
    args = kwargs.get("inputs")
    if args is None:
        raw = kwargs.get("input_str", "")
        if isinstance(raw, str):
            try:
                args = json.loads(raw)
            except (ValueError, TypeError):
                try:
                    args = ast.literal_eval(raw)
                except (ValueError, SyntaxError, TypeError):
                    args = raw
    return _truncate_value(args)


def _looks_like_error(result) -> bool:
    """判断工具结果是否隐含错误：dict 含 error 键 / 字符串以 error 开头。"""
    if isinstance(result, dict):
        return "error" in result or "error_code" in result
    return isinstance(result, str) and result.lower().startswith("error")


def _is_interrupt(value) -> bool:
    """判断是否为 LangGraph Interrupt（interrupt() 挂起时 langchain 把挂起当作
    工具结束/错误触发回调）。interrupt 不是真正的执行结果：工具尚未执行，
    结果要等 resume/审批恢复后才产生；标 error 会产生伪错误卡片。"""
    from langgraph.errors import GraphInterrupt as LGGI
    from langgraph.types import Interrupt
    if isinstance(value, (LGGI, Interrupt)):
        return True
    if isinstance(value, (tuple, list)):
        return any(_is_interrupt(v) for v in value)
    return False


def _tool_result(output):
    """提取工具返回：优先 ToolMessage.content（可能是 JSON/Python repr 字符串），解析为结构化值。

    on_tool_end 的 output 在 LangChain 中可能是 ToolMessage 实例（content 为
    工具返回的字符串，dict/list 可能被 JSON 或 Python repr 序列化），直接 str()
    会得到 repr 而非结构化结果；依次尝试 JSON / ast 解析成 dict/list，便于
    前端渲染结构化卡片与识别 error 状态。"""
    content = getattr(output, "content", output)
    if isinstance(content, str):
        for parser in (json.loads, ast.literal_eval):
            try:
                return _truncate_value(parser(content))
            except (ValueError, TypeError, SyntaxError):
                continue
        return _truncate_value(content)
    return _truncate_value(content)


class ToolCallRecorder:
    """收集一次图执行的工具调用（start/end 按 run_id 配对），供终态后落库工具卡片。

    只记录顺序与结构化数据，不落库；由 services/tool_cards.tool_message_rows
    在图到达终态后转成 Message。中断路径（interrupt 挂起）不落库，避免 resume
    重放产生重复卡片。"""

    def __init__(self):
        self._by_run: dict[str, dict] = {}
        self.order: list[dict] = []          # 按首次出现顺序

    def start(self, run_id: str, tool: str, args) -> None:
        rec = {"tool": tool, "args": args, "status": "running"}
        if run_id:
            self._by_run[run_id] = rec
        self.order.append(rec)

    def end(self, run_id: str, result, error: bool = False) -> None:
        rec = self._by_run.get(run_id) if run_id else None
        if rec is None:
            # 防御：run_id 缺失时匹配最后一个同工具 running
            for r in reversed(self.order):
                if r.get("status") == "running":
                    rec = r
                    break
        if rec is None:
            return
        rec["result"] = result
        rec["status"] = "error" if (error or _looks_like_error(result)) else "success"


# 跨 resume/审批共享的恢复期 recorder 注册表（按 trace_id 分组）。
# 多级 interrupt（high→critical）时，resume 确认执行成功的工具（如 create）与
# 后续审批恢复执行的工具（如 publish）需在最终终态一次性落库；若每次恢复用
# 独立 recorder，中间工具卡片会丢失（create 永远不落库）。
_resume_recorders: dict[str, ToolCallRecorder] = {}


def acquire_resume_recorder(trace_id: str) -> ToolCallRecorder:
    """按 trace_id 取共享的恢复期 recorder（不存在则建）。"""
    if not trace_id:
        return ToolCallRecorder()
    rec = _resume_recorders.get(trace_id)
    if rec is None:
        rec = ToolCallRecorder()
        _resume_recorders[trace_id] = rec
    return rec


def release_resume_recorder(trace_id: str) -> None:
    """终态落库后释放，避免注册表随 trace 累积泄漏。"""
    if trace_id:
        _resume_recorders.pop(trace_id, None)


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
    同时写入留痕。queue 可为 None（resume/审批路径无前端 SSE），此时只收集不推送。"""

    def __init__(self, queue: asyncio.Queue | None, trace_id: str,
                 recorder: ToolCallRecorder | None = None):
        self.queue = queue
        self.trace_id = trace_id
        self.recorder = recorder
        self._tool_runs: dict[str, str] = {}

    async def on_tool_start(self, serialized, input_str, **kwargs):
        name = serialized.get("name")
        run_id = str(kwargs.get("run_id", ""))
        self._tool_runs[run_id] = name
        args = _tool_args(**kwargs)
        if self.recorder is not None:
            self.recorder.start(run_id, name, args)
        collector.emit(self.trace_id, "tool_call",
                       {"event": "start", "name": name, "args": args})
        await self._push({"event": "tool_start", "tool": name, "args": args, "run_id": run_id})

    async def on_tool_end(self, output, **kwargs):
        run_id = str(kwargs.get("run_id", ""))
        if _is_interrupt(output):
            # interrupt() 挂起被 langchain 当作工具结束回调：非真正执行完成，忽略
            self._tool_runs.pop(run_id, None)
            return
        name = self._tool_runs.pop(run_id, "未知工具")
        result = _tool_result(output)
        if self.recorder is not None:
            self.recorder.end(run_id, result)
        collector.emit(self.trace_id, "tool_call",
                       {"event": "end", "name": name, "output": result})
        await self._push({"event": "tool_end", "tool": name, "result": result, "run_id": run_id})

    async def on_tool_error(self, error, **kwargs):
        """工具执行抛异常：卡片标红，不中断图执行。

        interrupt() 挂起不是真正的错误：工具尚未执行，结果要等 resume/审批恢复
        后才产生。若标 error 会产生「伪错误卡片」，且恢复重放会重复记录。"""
        run_id = str(kwargs.get("run_id", ""))
        if _is_interrupt(error):
            self._tool_runs.pop(run_id, None)
            return
        name = self._tool_runs.pop(run_id, "未知工具")
        result = str(error)[:_MAX_STR]
        if self.recorder is not None:
            self.recorder.end(run_id, result, error=True)
        collector.emit(self.trace_id, "tool_call",
                       {"event": "end", "name": name, "output": result, "error": True})
        await self._push({"event": "tool_end", "tool": name, "result": result,
                          "error": True, "run_id": run_id})

    async def _push(self, evt: dict) -> None:
        if self.queue is None:
            return
        try:
            self.queue.put_nowait(evt)
        except asyncio.QueueFull:
            pass
