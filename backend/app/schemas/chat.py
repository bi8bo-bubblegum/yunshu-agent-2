# backend/app/schemas/chat.py
from pydantic import BaseModel
from datetime import datetime

class ConversationCreate(BaseModel):
    title: str = "新对话"

class ConversationOut(BaseModel):
    id: str
    title: str
    summary: str | None = None
    created_at: datetime
    model_config = {"from_attributes": True}

class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    model_config = {"from_attributes": True}