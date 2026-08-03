# backend/app/models/configs.py
from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class AgentConfig(Base):
    __tablename__ = "agents"
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    model_key: Mapped[str] = mapped_column(String(64), default="default")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)  # system_prompt / tool_whitelist
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class McpServer(Base):
    __tablename__ = "mcp_servers"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(String(512))
    auth_type: Mapped[str] = mapped_column(String(16), default="none")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)