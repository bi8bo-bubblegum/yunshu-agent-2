# backend/app/agents/scheduling/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm.factory import ModelFactory
from app.tools.facade import facade
from app.agents.state import AgentState

SYSTEM_PROMPT = (
    "你是调度优化专家。结合记忆上下文与资源约束，给出排期/调度优化建议，"
    "包含时间线、资源分配、风险点。回答用中文。"
)

# 调度优化声明自己需要的内置工具
# MCP 服务绑定待任务 38.5 动态化后由 load_tools 统一加载
TOOL_NAMES = ["query_schedule", "adjust_schedule"]

MAX_TOOL_ROUNDS = 6  # 工具调用最大轮次，防 LLM 死循环

async def build_scheduling_agent():
    """调度优化子图：agent ↔ ToolNode 的 ReAct 循环，编译后作为节点嵌入父图。
    子图在模块内部独立构建，后续可差异化演进。"""
    # 本阶段仅加载内置工具；MCP 待任务 37/38 接入后改为 load_tools(db, ...)
    tools = [facade.to_langchain_tool(n) for n in TOOL_NAMES]

    async def agent_node(state: AgentState) -> dict:
        llm = ModelFactory.get_llm("scheduling").bind_tools(tools)
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