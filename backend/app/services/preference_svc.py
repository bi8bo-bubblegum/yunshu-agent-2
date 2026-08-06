# backend/app/services/preference_svc.py 追加：LLM 结构化提取
import logging
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.factory import ModelFactory
from app.repositories.preference_repo import PreferenceRepository

logger = logging.getLogger(__name__)

class PreferenceItem(BaseModel):
    """单条用户偏好"""
    category: Literal["style", "decision", "habit"] = Field(description="偏好类别")
    content: str = Field(description="偏好描述")
    confidence: float = Field(description="置信度 0~1")

class PreferenceOutput(BaseModel):
    """用户偏好提取结果"""
    preferences: list[PreferenceItem] = Field(default_factory=list, description="提取到的偏好列表，没有则为空")

async def extract_preferences(text: str) -> list[PreferenceItem]:
    llm = ModelFactory.get_llm().with_structured_output(PreferenceOutput)
    result = await llm.ainvoke(
        "你是用户偏好分析器。从对话中识别用户**稳定的长期偏好与习惯**。\n"
        "提取规则：\n"
        "1. 只提取跨多次出现、体现稳定倾向的内容（沟通风格/决策倾向/长期习惯）；\n"
        "2. 一次性决定、单次事件、临时选择（如“这次预算50000元”“本次用短信渠道”）不算偏好，不要提取；\n"
        "3. 没有稳定偏好时返回空列表。\n"
        f"偏好类别：style（沟通风格）/ decision（决策倾向）/ habit（习惯）。\n对话：{text}"
    )
    return result.preferences

async def extract_and_save(db: AsyncSession, user_id: str, text: str) -> None:
    repo = PreferenceRepository(db)
    try:
        prefs = await extract_preferences(text)
    except Exception as e:
        # LLM 输出校验失败不影响聊天主流程
        logger.warning("偏好提取 LLM 输出校验失败，跳过: %s", e)
        return
    for p in prefs:
        await repo.merge(user_id, p.category, p.content, p.confidence, "auto")
    if prefs:
        await repo.commit()
