# backend/app/agents/scheduling/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.factory import ModelFactory
from app.tools.loader import load_tools, load_mcp_tools_by_agent
from app.agents.state import AgentState
from app.agents.window import round_window
from app.agents.llm_stream import stream_llm

SYSTEM_PROMPT = (
    "你是一位资深排班调度优化专家。请结合【记忆上下文】中的偏好、经验、知识库与资源约束，"
    "输出可执行、可落地的排班 / 调度方案。\n"
    "\n"
    "## 任务流程（请严格按顺序执行）\n"
    "1. 先调用 query_schedule 查询目标部门与日期的现有排班，作为调整依据；\n"
    "2. 分析班次覆盖、人员负荷、技能匹配与合规风险；\n"
    "3. 若用户确认调整，调用 adjust_schedule 提交调整（高风险操作，系统会请求用户确认）。\n"
    "\n"
    "## 输出要求（务必逐项包含）\n"
    "1. 现状摘要：现有班次、人员、时段（引用查询结果）；\n"
    "2. 问题诊断：人力缺口 / 冗余、连班风险、覆盖不均等具体问题；\n"
    "3. 优化方案：给出时间线，以及每个班次的人员与时段调整；\n"
    "4. 资源分配：说明人员负荷是否均衡；\n"
    "5. 风险与备选：列出执行风险与应急预案。\n"
    "\n"
    "## 注意事项\n"
    "- 时间使用 HH:mm-HH:mm 格式，日期使用 YYYY-MM-DD 格式；\n"
    "- 调整必须基于查询到的真实排班，禁止凭空指定人员或时段；数据不足时明确说明；\n"
    "- 当用户提供新的查询条件（部门/日期变化）时，必须重新调用 query_schedule 获取最新数据，"
    "禁止沿用上一轮对话中的旧查询结果；\n"
    "- 回答使用中文，结构清晰；\n"
    "- 只调用调度相关工具，不要调用其他 agent 的工具。"
)

TOOL_NAMES = ["query_schedule", "adjust_schedule", "search_knowledge"]
AGENT_CODE = "scheduling"
MAX_TOOL_ROUNDS = 6


async def build_scheduling_agent(db: AsyncSession, enable_checkpointer: bool = False):
    """调度优化子图。内置工具硬编码声明，MCP 绑定从数据库动态读取。
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
        # 子图内 LLM token 只能由本节点主动推送。stream_llm 逐 chunk 产出并把文本
        # 经 config 注入的 SSE 队列实时转发给前端；同时合并 chunks 得到完整 AIMessage
        # （含 tool_calls）供 ReAct 循环判断下一步。内置超时降级：网关在流中途挂起时
        # 用已生成内容兜底，不无限阻塞。LLM 无 astream（如测试 mock）时降级为 ainvoke。
        sse_queue = ((config or {}).get("configurable") or {}).get("sse_queue")
        if hasattr(llm, "astream"):
            resp = await stream_llm(llm, msgs, sse_queue)
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
