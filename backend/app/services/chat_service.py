import json

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import Conversation, Message
from app.repositories.conversation_repo import ConversationRepository, MessageRepository
from app.agents.graph import graph

class ChatService:
    def __init__(self, db: AsyncSession):
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)

    async def _ensure_owned(self, conversation_id: str, user_id: str) -> Conversation:
        conv = await self.conversation_repo.get(conversation_id)
        if not conv or conv.user_id != user_id:
            raise HTTPException(status_code=404, detail="会话不存在")
        return conv

    async def stream_chat(self, user_id: str, conv_id: str, message: str):
        """SSE 事件异步生成器：start → token → done。"""
        await self._ensure_owned(user_id, conv_id)
        await self.message_repo.add(Message(conversation_id=conv_id, role="user", content=message))
        await self.message_repo.commit()
        yield json.dumps({"event": "start"}, ensure_ascii=False)
        result = await graph.ainvoke({
            "conversation_id": conv_id, "user_id": user_id,
            "user_message": message, "messages": [],
        })
        text = result.get("agent_response", "")
        await self.message_repo.add(Message(conversation_id=conv_id, role="assistant", content=text))
        await self.message_repo.commit()
        yield json.dumps({"event": "token", "content": text}, ensure_ascii=False)
        yield json.dumps({"event": "done"}, ensure_ascii=False)
