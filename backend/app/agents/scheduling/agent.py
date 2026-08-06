# backend/app/agents/scheduling/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.factory import ModelFactory
from app.tools.loader import load_tools, load_mcp_tools_by_agent
from app.agents.state import AgentState

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
    "- 回答使用中文，结构清晰；\n"
    "- 只调用调度相关工具，不要调用其他 agent 的工具。"
)

TOOL_NAMES = ["query_schedule", "adjust_schedule"]
AGENT_CODE = "scheduling"
MAX_TOOL_ROUNDS = 6


async def build_scheduling_agent(db: AsyncSession, enable_checkpointer: bool = False):
    """调度优化子图。内置工具硬编码声明，MCP 绑定从数据库动态读取。
    enable_checkpointer=True（父图嵌入场景）：compile(checkpointer=True) 继承父图
    checkpointer（由 wrap_subgraph 经 config 注入），子图内 interrupt 正常工作；
    默认 False（root 图/单测场景）不启用 checkpointer。"""
    mcp_server_names = await load_mcp_tools_by_agent(db, AGENT_CODE)
    tools = await load_tools(db, TOOL_NAMES, mcp_server_names)

    async def agent_node(state: AgentState) -> dict:
        llm = ModelFactory.get_llm(AGENT_CODE).bind_tools(tools)
        msgs = [
            SystemMessage(SYSTEM_PROMPT + "\n" + state.get("memory_context", "")),
            HumanMessage(state.get("user_message", "")),
        ] + state.get("messages", [])
        resp = await llm.ainvoke(msgs)
        return {"messages": [resp], "tool_rounds": 1}

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
