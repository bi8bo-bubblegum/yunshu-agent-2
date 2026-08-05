# backend/app/agents/marketing/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import HumanMessage, SystemMessage
from app.llm.factory import ModelFactory
from app.tools.facade import facade
from app.agents.state import AgentState

SYSTEM_PROMPT = (
    "你是营销助手。结合【记忆上下文】中的个人偏好、历史经验、知识库与企业数据，"
    "为用户策划营销方案。营销策略需包含目标、渠道、预算、预期效果。回答用中文。"
)

# 营销助手声明自己需要的内置工具（工具在任务 26.5 注册到 facade）
# MCP 服务绑定待任务 38.5 动态化后由 load_tools 统一加载
TOOL_NAMES = ["query_marketing_campaigns", "create_marketing_campaign", "publish_campaign"]

MAX_TOOL_ROUNDS = 6  # 工具调用最大轮次，防 LLM 死循环（每子 agent 可配置不同值）

async def build_marketing_agent():
    """营销助手子图：agent ↔ ToolNode 的 ReAct 循环，编译后作为节点嵌入父图。
    子图在模块内部独立构建，后续可差异化演进（换节点、加记忆节点、改路由等）。"""
    tools = [facade.to_langchain_tool(n) for n in TOOL_NAMES]

    async def agent_node(state: AgentState) -> dict:
        llm = ModelFactory.get_llm("marketing").bind_tools(tools)
        msgs = [
            SystemMessage(SYSTEM_PROMPT + "\n" + state.get("memory_context", "")),
            HumanMessage(state.get("user_message", "")),
        ] + state.get("messages", [])
        resp = await llm.ainvoke(msgs)
        return {"messages": [resp], "tool_rounds": 1}  # add reducer 自动累加

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            return "end"
        # 达到最大轮次即使仍要调工具也强制结束，防死循环
        return "tools" if state.get("tool_rounds", 0) < MAX_TOOL_ROUNDS else "end"

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(tools))
    g.set_entry_point("agent")
    g.add_edge("tools", "agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
    return g.compile()