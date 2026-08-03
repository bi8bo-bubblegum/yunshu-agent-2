from fastapi import HTTPException
from app.models.chat import Conversation, Message
from app.repositories.conversation_repo import ConversationRepository, MessageRepository

class ConversationService:
    def __init__(self, db):
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)

    async def create(self, user_id: str, title: str) -> Conversation:
        conv = Conversation(user_id=user_id, title=title)
        await self.conversation_repo.add(conv)
        await self.conversation_repo.commit()
        return conv

    async def list_by_user(self, user_id: str) -> list[Conversation]:
        return await self.conversation_repo.list_by_user(user_id)

    async def list_messages(self, user_id:str, conversation_id: str) -> list[Message]:
        conv = await self.conversation_repo.get(conversation_id)
        if not conv or conv.user_id != user_id:
            raise HTTPException(status_code=404, detail="会话不存在")
        return await self.message_repo.list_by_conversation(conversation_id)
