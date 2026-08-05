# backend/app/agents/scheduling/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.factory import ModelFactory
from app.tools.loader import load_tools, load_mcp_tools_by_agent
from app.agents.state import AgentState

SYSTEM_PROMPT = (
    "你是调度优化专家。结合记忆上下文与资源约束，给出排期/调度优化建议，"
    "包含时间线、资源分配、风险点。回答用中文。"
)

TOOL_NAMES = ["query_schedule", "adjust_schedule"]
AGENT_CODE = "scheduling"
MAX_TOOL_ROUNDS = 6


async def build_scheduling_agent(db: AsyncSession):
    """调度优化子图。内置工具硬编码声明，MCP 绑定从数据库动态读取。"""
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
    return g.compile()