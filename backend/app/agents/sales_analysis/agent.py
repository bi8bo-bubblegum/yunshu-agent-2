# backend/app/agents/sales_analysis/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.factory import ModelFactory
from app.tools.loader import load_tools, load_mcp_tools_by_agent
from app.agents.state import AgentState
from app.agents.window import round_window

SYSTEM_PROMPT = (
    "你是一位资深经营分析专家。请结合【记忆上下文】中的偏好、经验、知识库与企业数据，"
    "输出量化、可追溯、结论明确的经营分析。\n"
    "\n"
    "## 任务流程（请严格按顺序执行）\n"
    "1. 需要数据时，先调用 query_sales_data 查询指定指标与时间范围（可多次调用以覆盖多指标/多周期）；\n"
    "2. 基于查询结果做环比/结构/趋势分析，先算后说；\n"
    "3. 输出结论时注明数据来源与计算口径。\n"
    "\n"
    "## 输出要求（务必逐项包含）\n"
    "1. 核心指标概览：营收 / 订单 / 客户数及其环比变化；\n"
    "2. 趋势分析：识别上升或下降趋势，并给出可能原因；\n"
    "3. 结构分析：分渠道 / 品类 / 区域的贡献与变化（如有数据）；\n"
    "4. 风险与机会：至少 2 条量化风险与 2 条机会，每条附数据支撑；\n"
    "5. 行动建议：按优先级列出 3-5 条可落地建议；\n"
    "6. 数据口径：注明指标、时间范围与数据来源。\n"
    "\n"
    "## 注意事项\n"
    "- 数字保留整数或两位小数并注明单位；环比使用百分比；\n"
    "- 禁止臆造未查询到的数据；数据不足时明确说明缺口，并给出补数建议；\n"
    "- 当用户变更查询条件（指标/时间范围等）时，必须重新调用 query_sales_data 获取最新数据，"
    "禁止沿用上一轮对话中的旧结果；\n"
    "- 回答使用中文，善用小标题、列表与简单表格；\n"
    "- 只调用经营分析相关工具，不要调用其他 agent 的工具。"
)

TOOL_NAMES = ["query_sales_data", "delete_order"]
AGENT_CODE = "sales_analysis"
MAX_TOOL_ROUNDS = 6


async def build_sales_agent(db: AsyncSession, enable_checkpointer: bool = False):
    """经营分析子图。内置工具硬编码声明，MCP 绑定从数据库动态读取。
    enable_checkpointer=True（父图嵌入场景）：compile(checkpointer=True) 继承父图
    checkpointer（由 wrap_subgraph 经 config 注入），子图内 interrupt 正常工作；
    默认 False（root 图/单测场景）不启用 checkpointer。"""
    mcp_server_names = await load_mcp_tools_by_agent(db, AGENT_CODE)
    tools = await load_tools(db, TOOL_NAMES, mcp_server_names)

    async def agent_node(state: AgentState, config: RunnableConfig = None) -> dict:
        llm = ModelFactory.get_llm(AGENT_CODE).bind_tools(tools)
        # 只喂本轮上下文窗口（最近一条用户消息之后），历史由 memory 装配兜底，
        # 避免把会话全部历史 + 工具往返全量重发给 LLM（token 平方级浪费）
        msgs = [
            SystemMessage(SYSTEM_PROMPT + "\n" + state.get("memory_context", "")),
        ] + round_window(state.get("messages", []))
        # 流式生成：LangGraph 父图 stream_mode="messages" 不穿透编译子图内部，
        # 子图内 LLM token 只能由本节点主动推送。llm.astream 逐 chunk 产出，
        # 文本经 config 注入的 SSE 队列实时转发给前端；同时合并 chunks 得到
        # 完整 AIMessage（含 tool_calls），供 ReAct 循环判断下一步。
        # LLM 无 astream（如测试 mock）时降级为 ainvoke 一次性生成。
        sse_queue = ((config or {}).get("configurable") or {}).get("sse_queue")
        if hasattr(llm, "astream"):
            chunks: list = []
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
            resp = chunks[0]
            for c in chunks[1:]:
                resp = resp + c
        else:
            resp = await llm.ainvoke(msgs)
        out = {"messages": [resp], "tool_rounds": 1}
        # 快照本轮 agent 产出（agent 编码 + 文本）到 agent_outputs，供分段落库。
        # 仅当是「最终输出」时快照：带 tool_calls 的中间 LLM 输出（可能只是空行
        # 或过渡文本，如 '\n\n'）不是本轮 agent 的实质产出，若快照会生成空内容
        # 的 step 段落，刷新后表现为「中间消息丢失」。
        c = resp.content if hasattr(resp, "content") else ""
        if isinstance(c, list):
            c = "".join(str(b.get("text", "")) for b in c
                        if isinstance(b, dict) and b.get("type") == "text")
        if not getattr(resp, "tool_calls", None) and c.strip():
            out["agent_outputs"] = [{"agent": AGENT_CODE, "content": c}]
        return out

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "end"
        return "tools" if state.get("tool_rounds", 0) < MAX_TOOL_ROUNDS else "end"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(tools))
    g.set_entry_point("agent")
    g.add_edge("tools", "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    return g.compile(checkpointer=True if enable_checkpointer else None)
