# backend/app/agents/supervisor.py
from pydantic import BaseModel, Field
from app.llm.factory import ModelFactory

class RouteDecision(BaseModel):
    """意图路由结构化输出。agent 可选：注册的 agent 代码 + done（终止循环）。"""
    agent: str = Field(description="目标 agent 编码，从可选列表中选择；任务完成时返回 done")
    reason: str = Field(description="路由理由")
    confidence: float = Field(description="置信度 0~1")

ROUTE_SCHEMA = RouteDecision.model_json_schema()
AGENT_CODES = ["marketing", "sales_analysis", "scheduling", "general"]

async def route_decision(message: str, agents: list[str], model_key: str = "default") -> dict:
    """LLM 判断目标 agent，可选列表包含所有注册的 agent + done。
    agent 完成后再次调用此函数决定是否需要其他 agent 协作或结束。"""
    llm = ModelFactory.get_llm(model_key).with_structured_output(RouteDecision)
    try:
        result = await llm.ainvoke(
            f"你是多智能体系统的意图路由器。请根据用户消息与上一轮 agent 的输出，"
            f"从候选列表中选出唯一一个最合适的 agent 继续执行；"
            f"仅当任务已经完成、无需再调用任何 agent 时才返回 done。\n"
            f"\n"
            f"候选 agent：{agents}\n"
            f"\n"
            f"## 判断原则\n"
            f"1. 营销策划 / 活动管理类 → marketing；\n"
            f"2. 经营分析 / 销售数据 / 指标查询类 → sales_analysis；\n"
            f"3. 排班 / 调度 / 资源排期类 → scheduling；\n"
            f"4. 上一轮 agent 已完整回答用户诉求且无后续协作需求 → done；\n"
            f"5. 上一轮 agent 只完成部分诉求，或需要其他 agent 补充分析 → 选择对应 agent 继续。\n"
            f"\n"
            f"消息：{message}"
        )
        data = result.model_dump()
    except Exception:
        return {"agent": "done", "reason": "解析失败，默认结束", "confidence": 0.1}
    if data.get("agent") not in agents:
        data["agent"] = "done"
    return data
