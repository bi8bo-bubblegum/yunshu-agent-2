from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.factory import ModelFactory
from app.repositories.conversation_repo import ConversationRepository, MessageRepository


class SummaryOutput(BaseModel):
    summary: str = Field(description="简洁的中文摘要，保留关键决策、数字与结论")

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
    conv.summary = await summarize_text(old_summary + text)
    await conv_repo.commit()

