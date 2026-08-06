# backend/app/api/chat.py —— 薄路由：只包装 SSE 流式响应
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphInterrupt
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.chat_service import ChatService

router = APIRouter(prefix="/api/chat", tags=["chat"])

class ChatRequest(BaseModel):
    conversation_id: str
    message: str


class ResumeRequest(BaseModel):
    conversation_id: str
    approved: bool  # high 风险即时确认：True=执行 / False=驳回

def get_chat_service(db: AsyncSession = Depends(get_db)) -> ChatService:
    return ChatService(db)

@router.post("/completions")
async def chat_completions(body: ChatRequest, svc: ChatService = Depends(get_chat_service), user: User = Depends(get_current_user)):
    async def event_stream():
        try:
            async for evt in svc.stream_chat(user.id, body.conversation_id, body.message):
                yield f"data: {evt}\n\n"
        except GraphInterrupt as e:
            # high 风险工具 interrupt 冻结：向前端发送即时确认事件
            payload = e.args[0] if e.args else {}
            if isinstance(payload, dict):
                payload.setdefault("conversation_id", body.conversation_id)
            yield f"data: {json.dumps({'event': 'confirm_required', 'payload': payload}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'event': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.post("/resume")
async def chat_resume(body: ResumeRequest, svc: ChatService = Depends(get_chat_service), user: User = Depends(get_current_user)):
    """high 风险工具 interrupt 确认后恢复图执行。"""
    return await svc.resume(user.id, body.conversation_id, body.approved)