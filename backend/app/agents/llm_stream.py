# backend/app/agents/llm_stream.py —— 子图 agent 流式生成（带超时降级）
import asyncio
import logging

from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)

# 单次 agent LLM 流式生成限时。网关偶发在流中途挂起（不发后续 chunk 也不断连），
# 无保护时 async for 会挂到 httpx 读间隔超时（factory 里 timeout=120，指相邻字节
# 最大间隔而非总时长，流中途无字节时不触发），stream_chat / resume 长时间无响应。
# 真实事故：resume 恢复图执行后 agent 二次生成挂起 >170s，前端永不返回、消息不落库，
# 而 create 工具已在 trace 中成功执行（C50000）。超时后降级为已收集 chunk 兜底输出，
# 不抛异常中断图执行，保证流程可控时限。
AGENT_LLM_TIMEOUT = 60.0


async def stream_llm(llm, msgs, sse_queue=None, timeout: float = AGENT_LLM_TIMEOUT) -> AIMessage:
    """流式生成带超时保护：逐 chunk 收集并推送 SSE token，超时用已收集内容降级。

    - 正常：合并全部 chunks 返回完整 AIMessage（含 tool_calls），供 ReAct 循环继续；
    - 中途超时：保留已收集 chunks 合并返回（内容可能不完整，但图能继续，不会无限等）；
    - 一个 chunk 都没收到（网关完全无响应）：返回降级提示消息，避免图崩溃。
    LLM 无 astream（测试 mock）由调用方走 ainvoke，不调用本函数。

    timeout 可注入（测试用小值快速触发），生产默认 AGENT_LLM_TIMEOUT。
    """
    chunks: list = []

    async def _collect():
        async for chunk in llm.astream(msgs):
            chunks.append(chunk)
            c = chunk.content
            if isinstance(c, list):
                c = "".join(str(b.get("text", "")) for b in c
                            if isinstance(b, dict) and b.get("type") == "text")
            if c and sse_queue is not None:
                try:
                    sse_queue.put_nowait({"event": "token", "content": c})
                except Exception:
                    pass

    try:
        await asyncio.wait_for(_collect(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("agent LLM 流式生成超时(%ss)，用已生成内容降级（chunks=%d）",
                       timeout, len(chunks))
    if not chunks:
        # 一个 chunk 都没收到：返回降级提示（无 tool_calls），ReAct 走 end 结束本轮，
        # 用户看到明确提示而非前端死等
        return AIMessage(content="（模型生成超时，请稍后重试或查看执行详情）")
    resp = chunks[0]
    for c in chunks[1:]:
        resp = resp + c
    return resp
