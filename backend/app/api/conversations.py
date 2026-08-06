# backend/app/api/conversations.py —— 薄路由
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.schemas.chat import ConversationCreate, ConversationOut, MessageOut
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

def get_conv_service(db: AsyncSession = Depends(get_db)) -> ConversationService:
    return ConversationService(db)

@router.post("", response_model=ConversationOut)
async def create_conversation(body: ConversationCreate, svc: ConversationService = Depends(get_conv_service), user: User = Depends(get_current_user)):
    return await svc.create(user.id, body.title)

@router.get("", response_model=list[ConversationOut])
async def list_conversations(svc: ConversationService = Depends(get_conv_service), user: User = Depends(get_current_user)):
    return await svc.list_by_user(user.id)

@router.get("/{conv_id}/messages", response_model=list[MessageOut])
async def list_messages(conv_id: str, svc: ConversationService = Depends(get_conv_service), user: User = Depends(get_current_user)):
    return await svc.list_messages(user.id, conv_id)

@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str, svc: ConversationService = Depends(get_conv_service), user: User = Depends(get_current_user)):
    """删除会话及其消息（他人会话返回 404，不泄露存在性）。"""
    await svc.delete(user.id, conv_id)
    return {"ok": True}
