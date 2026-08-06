# backend/app/services/experience_svc.py
import logging
from datetime import date
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.experience import Experience
from app.repositories.experience_repo import ExperienceRepository
from app.services.embedding import embed_texts
from app.llm.factory import ModelFactory

logger = logging.getLogger(__name__)

class DistillOutput(BaseModel):
    """经验提炼结构化输出"""
    title: str | None = Field(default=None, description="标题，无价值时为 null")
    summary: str = Field(default="", description="要点摘要")
    content: str = Field(default="", description="完整决策过程")
    tags: list[str] = Field(default_factory=list, description="业务标签")
    event_time: date | None = Field(default=None, description="事件日期 YYYY-MM-DD，营销/策略类必填")
    result_metrics: dict | None = Field(default=None, description="效果指标，营销/策略类必填")

async def distill_experience(text: str, user_id: str, trace_id: str) -> Experience | None:
    llm = ModelFactory.get_llm().with_structured_output(DistillOutput)
    prompt = (
        "你是企业经验提炼器。从对话中提炼有价值的历史决策/策略/教训。"
        "营销/策略类必须包含 event_time 和 result_metrics，否则视为无价值将 title 设为 null。"
        "\n对话：" + text[:6000]
    )
    # LLM 偶发返回非法日期（如 0000-01-01）会导致 pydantic 校验失败，
    # 重试一次并强调日期约束；仍失败则放弃本条经验，不影响聊天主流程
    result = None
    for attempt, extra in enumerate((
        "",
        "\n注意：event_time 必须是 1900-01-01 至 2100-12-31 之间的真实日期（如 2024-10-01），"
        "禁止使用 0000-01-01 等非法日期；没有有效日期时置为 null。",
    )):
        try:
            result = await llm.ainvoke(prompt + extra)
            break
        except Exception as e:
            logger.warning("经验提炼 LLM 输出校验失败（第 %d 次）: %s", attempt + 1, e)
    if not result.title:
        return None
    vec = (await embed_texts([f"{result.title} {result.summary}"]))[0]
    return Experience(
        owner_id=user_id, scope="personal", status="draft",
        title=result.title, summary=result.summary, content=result.content,
        tags=result.tags, event_time=result.event_time, result_metrics=result.result_metrics,
        source_trace_id=trace_id, embedding=vec,
    )

async def save_personal_experience(db: AsyncSession, exp: Experience) -> None:
    repo = ExperienceRepository(db)
    await repo.add(exp)
    await repo.commit()
