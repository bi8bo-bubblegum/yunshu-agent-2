from sqlalchemy import select, func
from app.models.chat import Conversation, Message
from app.repositories.base import BaseRepository

class ConversationRepository(BaseRepository):
    model = Conversation

    async def list_by_user(self, user_id: str) -> list[Conversation]:
        stmt = select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.created_at.desc())
        return list((await self.db.scalars(stmt)).all())

class MessageRepository(BaseRepository):
    model = Message

    async def list_by_conversation(self, conversation_id: str) -> list[Message]:
        stmt = select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
        return list((await self.db.scalars(stmt)).all())

    async def list_recent(self, conversation_id: str, limit: int = 20) -> list[Message]:
        return list((await self.db.scalars(
            select(Message).where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc()).limit(limit)
        )).all())

    async def count_in_conversation(self, conversation_id: str) -> int:
        return await self.count(conversation_id=conversation_id)
