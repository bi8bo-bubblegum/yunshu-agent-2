# backend/app/agents/supervisor.py
from pydantic import BaseModel, Field
from app.llm.factory import ModelFactory

class RouteDecision(BaseModel):
    """意图路由结构化输出"""
    agent: str = Field(description="目标 agent 编码，从可选列表中选择")
    reason: str = Field(description="路由理由")
    confidence: float = Field(description="置信度 0~1")

class DecideDoneOutput(BaseModel):
    """判断回答是否完整的结构化输出"""
    done: bool = Field(description="是否已完整解决问题")

ROUTE_SCHEMA = RouteDecision.model_json_schema()
AGENT_CODES = ["marketing", "sales_analysis", "scheduling", "general"]

async def route_decision(message: str, agents: list[str], model_key: str = "default") -> dict:
    llm = ModelFactory.get_llm(model_key).with_structured_output(RouteDecision)
    try:
        result = await llm.ainvoke(
            f"你是意图路由器。从用户消息判断交给哪个 agent，可选：{agents}。\n消息：{message}"
        )
        data = result.model_dump()
    except Exception:
        return {"agent": "general", "reason": "解析失败兜底", "confidence": 0.1}
    if data.get("agent") not in agents:
        data["agent"] = "general"
    return data

async def decide_done(agent_response: str, model_key: str = "default") -> bool:
    llm = ModelFactory.get_llm(model_key).with_structured_output(DecideDoneOutput)
    result = await llm.ainvoke(
        f"判断以下回答是否已完整解决问题。\n回答：{agent_response[:2000]}"
    )
    return result.done