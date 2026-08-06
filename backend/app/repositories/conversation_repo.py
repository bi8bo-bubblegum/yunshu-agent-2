from sqlalchemy import delete, select, func
from app.models.chat import Conversation, Message
from app.repositories.base import BaseRepository

class ConversationRepository(BaseRepository[Conversation]):
    model = Conversation

    async def list_by_user(self, user_id: str) -> list[Conversation]:
        stmt = select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.created_at.desc())
        return list((await self.db.scalars(stmt)).all())

class MessageRepository(BaseRepository[Message]):
    model = Message

    async def list_by_user(self, user_id: str) -> list[Message]:
        """用户跨全部会话的消息（按时间正序）。偏好按人累计，不受会话边界限制。"""
        conv_ids = (await self.db.scalars(
            select(Conversation.id).where(Conversation.user_id == user_id)
        )).all()
        if not conv_ids:
            return []
        stmt = (
            select(Message)
            .where(Message.conversation_id.in_([str(c) for c in conv_ids]))
            .order_by(Message.created_at, Message.seq)
        )
        return list((await self.db.scalars(stmt)).all())

    async def delete_by_conversation(self, conversation_id: str) -> None:
        await self.db.execute(delete(Message).where(Message.conversation_id == conversation_id))

    async def list_by_conversation(self, conversation_id: str) -> list[Message]:
        stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.seq)
        return list((await self.db.scalars(stmt)).all())

    async def list_recent(self, conversation_id: str, limit: int = 20) -> list[Message]:
        return list((await self.db.scalars(
            select(Message).where(Message.conversation_id == conversation_id)
            .order_by(Message.seq.desc()).limit(limit)
        )).all())

    async def count_in_conversation(self, conversation_id: str) -> int:
        return await self.count(conversation_id=conversation_id)
