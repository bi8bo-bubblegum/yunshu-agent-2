import json

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.assembly import assemble_memory
from app.memory.short_term import build_context
from app.models.chat import Conversation, Message
from app.repositories.conversation_repo import ConversationRepository, MessageRepository
from app.agents.graph import graph
from app.repositories.user_repo import UserRepository
from app.services.experience_svc import distill_experience, save_personal_experience
from app.services.preference_svc import extract_and_save
from app.services.summary import maybe_roll_summary


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = MessageRepository(db)
        self.user_repo = UserRepository(db)

    async def _ensure_owned(self, conversation_id: str, user_id: str) -> Conversation:
        conv = await self.conversation_repo.get(conversation_id)
        if not conv or conv.user_id != user_id:
            raise HTTPException(status_code=404, detail="会话不存在")
        return conv

    async def stream_chat(self, user_id: str, conv_id: str, message: str):
        """SSE 事件异步生成器：start → token → done。"""
        await self._ensure_owned(conv_id, user_id)
        await self.message_repo.add(Message(conversation_id=conv_id, role="user", content=message))
        await self.message_repo.commit()
        yield json.dumps({"event": "start"}, ensure_ascii=False)
        user = await self.user_repo.get(user_id)
        if user and user.department_id:
            dep_id = user.department_id
        else:
            dep_id = None
        mem = await assemble_memory(self.db, user_id, conv_id, dep_id , message)
        result = await graph.ainvoke({
            "conversation_id": conv_id, "user_id": user_id,
            "user_message": message, "memory_context": mem, "messages": [],
        })
        text = result.get("agent_response", "")
        await self.message_repo.add(Message(conversation_id=conv_id, role="assistant", content=text))
        await self.message_repo.commit()
        dialog = f"用户：{message}\n助手：{text}"
        await extract_and_save(self.db, user_id, dialog)
        exp = await distill_experience(dialog, user_id, result.get("trace_id", ""))
        if exp:
            await save_personal_experience(self.db, exp)
        await maybe_roll_summary(self.db, conv_id)
        yield json.dumps({"event": "token", "content": text}, ensure_ascii=False)
        yield json.dumps({"event": "done"}, ensure_ascii=False)
