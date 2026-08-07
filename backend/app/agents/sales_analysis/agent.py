# backend/app/agents/sales_analysis/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.factory import ModelFactory
from app.tools.loader import load_tools, load_mcp_tools_by_agent
from app.agents.state import AgentState

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

    async def agent_node(state: AgentState) -> dict:
        llm = ModelFactory.get_llm(AGENT_CODE).bind_tools(tools)
        msgs = [
            SystemMessage(SYSTEM_PROMPT + "\n" + state.get("memory_context", "")),
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
