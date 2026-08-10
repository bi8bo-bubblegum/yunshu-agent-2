# backend/app/schemas/chat.py
from pydantic import BaseModel, Field
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
    # 分段落库元数据：{agent: 编码, segment: "final"|"step"}，历史消息为 null
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    model_config = {"from_attributes": True}