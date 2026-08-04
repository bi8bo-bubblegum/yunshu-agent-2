from sys import prefix

from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.conversation_repo import ConversationRepository, MessageRepository

async def build_context(db: AsyncSession, conversation_id: str, recent_rounds: int = 10) -> str:
    conv_repo = ConversationRepository(db)
    msg_repo = MessageRepository(db)
    conv = await conv_repo.get(conversation_id)
    if not conv:
        return ""
    msgs = await msg_repo.list_recent(conversation_id, recent_rounds * 2)
    msgs.reverse()
    lines = [f"{m.role}: {m.content}" for m in msgs]
    pre = f"[历史摘要] {conv.summary}\n" if conv.summary else ""
    return pre + "\n".join(lines)
