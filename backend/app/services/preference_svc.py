# backend/app/services/preference_svc.py —— 批量偏好分析
import logging
from typing import Literal
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.factory import ModelFactory
from app.repositories.preference_repo import PreferenceRepository

logger = logging.getLogger(__name__)

# 每达到该数量的用户消息时，对最近一批对话做一次增量偏好分析
BATCH_SIZE = 10

class PreferenceItem(BaseModel):
    """单条用户偏好"""
    category: Literal["style", "decision", "habit"] = Field(description="偏好类别")
    content: str = Field(description="偏好描述")
    confidence: float = Field(description="置信度 0~1")

class PreferenceOutput(BaseModel):
    """用户偏好提取结果"""
    preferences: list[PreferenceItem] = Field(default_factory=list, description="提取到的偏好列表，没有则为空")


async def extract_preferences_from_dialogs(dialogs: list[str]) -> list[PreferenceItem]:
    """对一批对话做偏好分析：只提取多轮中反复出现、体现稳定倾向的偏好。"""
    llm = ModelFactory.get_llm().with_structured_output(PreferenceOutput)
    text = "\n\n---\n\n".join(f"第{i + 1}轮：\n{d}" for i, d in enumerate(dialogs))
    result = await llm.ainvoke(
        "你是用户偏好分析器。以下是同一用户的连续多轮对话，请识别其稳定的长期偏好与习惯。\n"
        "提取规则：\n"
        "1. 只提取在多轮对话中反复出现、体现稳定倾向的内容（沟通风格/决策倾向/长期习惯）；\n"
        "2. 只出现一次的一次性决定、临时选择（如“这次预算50000元”“本次用短信渠道”）不算偏好，不要提取；\n"
        "3. 没有稳定偏好时返回空列表。\n"
        "偏好类别：style（沟通风格）/ decision（决策倾向）/ habit（习惯）。\n"
        f"对话：\n{text}"
    )
    return result.preferences


async def maybe_extract_batch(db: AsyncSession, user_id: str, conversation_id: str) -> None:
    """增量批次偏好分析：用户消息达到 BATCH_SIZE 的整数倍时，
    对最近一批（不含此前已分析过的）对话做一次分析并合并入库。
    消息按 user_id 跨全部会话累计——偏好属于个人，不受会话边界影响。"""
    from app.repositories.conversation_repo import MessageRepository
    msgs = await MessageRepository(db).list_by_user(user_id)
    user_msgs = [m for m in msgs if m.role == "user"]
    # 未到批次边界则不触发；每批只分析一次（窗口 = 最近 BATCH_SIZE 条用户消息）
    if len(user_msgs) < BATCH_SIZE or len(user_msgs) % BATCH_SIZE != 0:
        return
    recent = user_msgs[-BATCH_SIZE:]
    # 按会话分组，配对时在同一会话内找该用户消息之后的助手回复
    by_conv: dict[str, list] = {}
    for m in msgs:
        by_conv.setdefault(m.conversation_id, []).append(m)
    dialogs = []
    for um in recent:
        dialog = f"用户：{um.content}"
        conv_msgs = by_conv.get(um.conversation_id, [])
        idx = conv_msgs.index(um)
        for m in conv_msgs[idx + 1:]:
            if m.role == "assistant":
                dialog += f"\n助手：{m.content}"
                break
        dialogs.append(dialog)
    try:
        prefs = await extract_preferences_from_dialogs(dialogs)
    except Exception as e:
        # LLM 输出校验失败不影响聊天主流程
        logger.warning("批量偏好提取 LLM 调用失败，跳过: %s", e)
        return
    repo = PreferenceRepository(db)
    for p in prefs:
        await repo.merge(user_id, p.category, p.content, p.confidence, "auto")
    if prefs:
        await repo.commit()
