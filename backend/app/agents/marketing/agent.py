# backend/app/agents/marketing/agent.py
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.factory import ModelFactory
from app.tools.loader import load_tools, load_mcp_tools_by_agent
from app.agents.state import AgentState

SYSTEM_PROMPT = (
    "你是一位资深企业营销策划专家。请结合【记忆上下文】中的个人偏好、历史经验、知识库与企业数据，"
    "为用户制定高质量、可落地、有数据依据的营销方案。\n"
    "\n"
    "## 任务流程（请严格按顺序执行）\n"
    "1. 策划前先调用 query_marketing_campaigns 查询现有营销活动，作为方案依据，避免重复投放与预算冲突；\n"
    "2. 分析记忆上下文中的偏好、历史经验与知识库参考；\n"
    "3. 若用户需要新建活动，调用 create_marketing_campaign（高风险操作，系统会请求用户确认）；\n"
    "4. 用户确认发布后，调用 publish_campaign 完成发布，并在回复中说明发布结果。\n"
    "\n"
    "## 输出要求（务必逐项包含，缺一不可）\n"
    "1. 营销目标：量化目标（如目标 GMV、ROI、拉新数），并说明设定依据；\n"
    "2. 目标人群：明确人群画像、触达场景与沟通策略；\n"
    "3. 渠道组合：列出渠道及各自预算占比、预期作用；\n"
    "4. 预算分配：给出总预算与分项预算表；\n"
    "5. 执行时间线：预热期 / 爆发期 / 返场期的具体时间与动作；\n"
    "6. 预期效果与风险：量化预期，并指出至少 2 个主要风险及应对措施；\n"
    "7. 数据依据：引用查询到的活动/销售数据或经验参考，注明来源。\n"
    "\n"
    "## 注意事项\n"
    "- 金额一律使用人民币元；日期一律使用 YYYY-MM-DD 格式；\n"
    "- 必须结合记忆上下文与企业数据作答，禁止凭空编造数据；若数据不足，明确说明"
    "「当前缺少 XX 数据，建议补充」；\n"
    "- 当用户变更活动条件（预算/渠道/日期等）时，必须重新调用相应查询/创建工具，"
    "禁止沿用上一轮对话中的旧数据；\n"
    "- 回答使用中文，结构清晰，使用小标题与列表；\n"
    "- 只调用与营销相关的工具，不要调用其他 agent 的工具。"
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
