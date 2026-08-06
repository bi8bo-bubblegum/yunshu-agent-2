import asyncio
import logging
from collections.abc import Callable

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.llm.factory import ModelFactory
from app.repositories.conversation_repo import ConversationRepository, MessageRepository

logger = logging.getLogger(__name__)


class SummaryOutput(BaseModel):
    summary: str = Field(description="简洁的中文摘要，保留关键决策、数字与结论")


class TitleOutput(BaseModel):
    title: str = Field(description="简洁的中文会话标题，10~20 字，概括消息核心意图")


# 后台标题生成任务管理：持有任务引用防止 GC 提前取消；按会话去重避免重复调用
_bg_title_tasks: set[asyncio.Task] = set()
_inflight_titles: set[str] = set()


async def auto_title_async(conv_id: str, message: str) -> str | None:
    """生成会话标题并写库（独立 Session）。仅在标题仍为默认值时写入，返回标题或 None。"""
    try:
        new_title = await generate_title(message)
        if not new_title or new_title == "新对话":
            return None
        async with SessionLocal() as db:
            repo = ConversationRepository(db)
            conv = await repo.get(conv_id)
            if conv and conv.title in ("新对话", "", None):
                conv.title = new_title
                await repo.commit()
                return new_title
    except Exception as e:
        logger.warning("后台标题生成失败（已降级）: %s", e)
    return None


def schedule_title_generation(conv_id: str, message: str,
                              on_done: Callable[[str | None], None] | None = None) -> None:
    """后台调度标题生成：持有任务引用防 GC，同一会话在途时不重复调度。"""
    if conv_id in _inflight_titles:
        return
    _inflight_titles.add(conv_id)

    async def _run():
        try:
            title = await auto_title_async(conv_id, message)
            if on_done:
                on_done(title)
        finally:
            _inflight_titles.discard(conv_id)

    task = asyncio.create_task(_run())
    _bg_title_tasks.add(task)
    task.add_done_callback(_bg_title_tasks.discard)


async def generate_title(message: str) -> str:
    """根据用户消息生成简洁会话标题（首次发送时调用）。"""
    llm = ModelFactory.get_llm().with_structured_output(TitleOutput)
    prompt = (
        "根据用户消息为会话生成一个简洁的中文标题（10~20 字），"
        "概括消息的核心意图，不要包含引号、标点或多余修饰。\n消息："
        + message[:500]
    )
    # LLM 偶发解析失败：重试一次并强调输出约束；仍失败则兜底取消息前 20 字，
    # 保证真实消息一定会获得非默认标题
    for attempt, hint in enumerate((
        "",
        "\n注意：只输出标题文本本身，不要加引号、解释或额外内容。",
    )):
        try:
            result = await llm.ainvoke(prompt + hint)
            title = (result.title or "").strip()[:30]
            if title:
                return title
        except Exception as e:
            logger.warning("标题生成 LLM 调用失败（第 %d 次）: %s", attempt + 1, e)
    fallback = message.strip()[:20]
    return fallback or "新对话"


async def summarize_text(messages_text: str) -> str:
    llm = ModelFactory.get_llm().with_structured_output(SummaryOutput)
    result = await llm.ainvoke(
        f"将以下对话压缩为简洁的中文摘要，保留关键决策、数字与结论：\n{messages_text}"
    )
    return result.summary

async def maybe_roll_summary(db: AsyncSession, conversation_id: str, force: bool = False, max_messages: int = 20) -> None:
    conv_repo = ConversationRepository(db)
    msg_repo = MessageRepository(db)
    conv = await conv_repo.get(conversation_id)
    count = await msg_repo.count(conversation_id=conversation_id)
    if not force and count < max_messages:
        return
    recent = await msg_repo.list_recent(conversation_id, 10)
    text = "\n".join(f"{m.role}: {m.content}" for m in reversed(recent))
    old_summary = f"已有摘要：{conv.summary}\n" if conv.summary else ""
    try:
        conv.summary = await summarize_text(old_summary + text)
    except Exception as e:
        # 摘要 LLM 失败保留旧摘要，不阻塞聊天
        logger.warning("滚动摘要 LLM 调用失败，保留旧摘要: %s", e)
        return
    await conv_repo.commit()
