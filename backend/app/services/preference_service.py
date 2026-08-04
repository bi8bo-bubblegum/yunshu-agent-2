# backend/app/services/preference_svc.py 追加：LLM 结构化提取
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.factory import ModelFactory
from app.repositories.preference_repo import PreferenceRepository

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
        f"你是用户偏好分析器。根据对话提取用户偏好，提取偏好类别（style/decision/habit）、"
        f"偏好内容和置信度。没有偏好时返回空列表。\n对话：{text}"
    )
    return result.preferences

async def extract_and_save(db: AsyncSession, user_id: str, text: str) -> None:
    repo = PreferenceRepository(db)
    prefs = await extract_preferences(text)
    for p in prefs:
        await repo.merge(user_id, p.category, p.content, p.confidence, "auto")
    if prefs:
        await repo.commit()