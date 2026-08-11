# backend/app/agents/supervisor.py
import logging

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from app.llm.factory import ModelFactory
from app.llm.date_context import current_date_context

logger = logging.getLogger(__name__)

class RouteDecision(BaseModel):
    """意图路由结构化输出。agent 可选：注册的 agent 代码 + done（终止循环）。"""
    agent: str = Field(description="目标 agent 编码，从可选列表中选择；任务完成时返回 done")
    reason: str = Field(description="路由理由")
    confidence: float = Field(description="置信度 0~1")

ROUTE_SCHEMA = RouteDecision.model_json_schema()

AGENT_KEYWORDS = {
    "marketing": ["营销", "活动", "推广", "策划", "投放", "广告", "campaign", "marketing"],
    "sales_analysis": ["销售", "经营", "营收", "订单", "客户", "指标", "数据", "分析", "报表", "sales", "revenue", "order"],
    "scheduling": ["排班", "班次", "调度", "排期", "值班", "工时", "schedule", "shift"],
}


# 路由系统指令：角色设定、候选列表、判断原则、当前日期全部放 SystemMessage，
# 用户真实输入（本轮消息 + 上一轮 agent 输出）单独放 HumanMessage。
# 与子 agent（marketing/sales_analysis/scheduling）的 SystemMessage + memory 模式对齐，
# 避免「路由规则」和「待路由内容」混在一条 user 消息里，模型可更准确区分指令与内容。
SYSTEM_ROUTER_PROMPT = (
    "你是多智能体系统的意图路由器。请根据用户消息与上一轮 agent 的输出，"
    "从候选列表中选出唯一一个最合适的 agent 继续执行。\n"
    "\n"
    "候选 agent：{agents}\n"
    "\n"
    "## 判断原则\n"
    "1. 营销策划 / 活动管理类 → marketing；\n"
    "2. 经营分析 / 销售数据 / 指标查询类 → sales_analysis；\n"
    "3. 排班 / 调度 / 资源排期类 → scheduling；\n"
    "4. 用户提出新的诉求或补充信息，根据意图选择对应 agent；\n"
    "5. 上一轮 agent 只完成部分诉求，或需要其他 agent 补充分析 → 选择对应 agent 继续。\n"
    "\n"
    "注意：始终选择一个具体的 agent 编码（如 marketing），不要返回 done。"
    "任务完成与否由 agent 自行判断，你只负责路由。\n"
    "\n"
    "{date}"
)


def _infer_agent(message: str, agents: list[str]) -> str | None:
    """结构化输出解析失败时，按消息关键词兜底推断目标 agent。"""
    text = message.lower()
    for code in agents:
        for kw in AGENT_KEYWORDS.get(code, []):
            if kw in text:
                return code
    return None


def fallback_decision(message: str, agents: list[str]) -> dict:
    """路由降级兜底：LLM 超时/不可用时按关键词推断目标 agent，避免路由环节挂起。"""
    agent = _infer_agent(message, agents)
    return {"agent": agent or "done", "reason": "路由降级（LLM 超时），按关键词兜底", "confidence": 0.1}


def _fuzzy_match(agent: str, agents: list[str]) -> str | None:
    """LLM 返回了候选列表之外的代码时，做近似匹配（如 schedule → scheduling）。"""
    a = (agent or "").lower().replace("-", "_").replace(" ", "_")
    for code in agents:
        if a == code or code in a or a in code:
            return code
    return None


async def route_decision(message: str, agents: list[str], model_key: str = "default") -> dict:
    """LLM 判断目标 agent，可选列表包含所有注册的 agent + done。
    agent 完成后再次调用此函数决定是否需要其他 agent 协作或结束。"""
    llm = ModelFactory.get_llm(model_key).with_structured_output(RouteDecision)
    system = SYSTEM_ROUTER_PROMPT.format(agents=agents, date=current_date_context())
    data = None
    # 结构化输出偶发解析失败：重试一次（强调取值约束），仍失败再走关键词兜底
    for attempt, hint in enumerate((
        "",
        "\n注意：agent 字段必须严格等于候选列表中的一个代码（如 scheduling），不要返回列表之外的值或解释性文字。",
    )):
        try:
            result = await llm.ainvoke([
                SystemMessage(content=system + hint),
                HumanMessage(content=message),
            ])
            data = result.model_dump()
            break
        except Exception as e:
            logger.warning("路由决策解析失败（第 %d 次）: %s", attempt + 1, e)
    if data is None:
        agent = _infer_agent(message, agents)
        return {"agent": agent or "done", "reason": "解析失败，按消息关键词兜底", "confidence": 0.2}
    if data.get("agent") not in agents:
        data["agent"] = _fuzzy_match(data.get("agent"), agents) or _infer_agent(message, agents) or "done"
    return data
