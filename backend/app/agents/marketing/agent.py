# backend/app/agents/marketing/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.factory import ModelFactory
from app.tools.loader import load_tools, load_mcp_tools_by_agent
from app.agents.state import AgentState

SYSTEM_PROMPT = (
    "你是营销助手。结合【记忆上下文】中的个人偏好、历史经验、知识库与企业数据，"
    "为用户策划营销方案。营销策略需包含目标、渠道、预算、预期效果。回答用中文。"
)

# 内置工具仍硬编码（新增内置工具本身就需要写代码）
TOOL_NAMES = ["query_marketing_campaigns", "create_marketing_campaign", "publish_campaign"]
AGENT_CODE = "marketing"
MAX_TOOL_ROUNDS = 6


async def build_marketing_agent(db: AsyncSession, enable_checkpointer: bool = False):
    """营销助手子图。内置工具硬编码声明，MCP 绑定从数据库动态读取。
    enable_checkpointer=True（父图嵌入场景）：compile(checkpointer=True) 继承父图
    checkpointer（由 wrap_subgraph 经 config 注入），子图内 interrupt 正常工作；
    默认 False（root 图/单测场景）不启用 checkpointer。"""
    # 1. 内置工具（硬编码）
    # 2. MCP 绑定（从数据库读取，替代硬编码的 MCP_SERVER_NAMES）
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