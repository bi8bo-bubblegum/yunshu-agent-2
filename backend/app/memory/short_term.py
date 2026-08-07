from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.conversation_repo import ConversationRepository, MessageRepository

async def build_context(db: AsyncSession, conversation_id: str, recent_rounds: int = 10) -> str:
    """短期记忆：只返回窗口外的滚动摘要。

    最近 N 轮原文已由主图通过 state.messages 以真实消息注入 agent，
    这里不再重复输出原文，避免同一内容喂两遍；滚动摘要覆盖窗口外压缩历史。
    """
    conv = await ConversationRepository(db).get(conversation_id)
    if not conv or not conv.summary:
        return ""
    return f"【历史摘要】\n{conv.summary}"
