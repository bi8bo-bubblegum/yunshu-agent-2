# backend/app/models/configs.py
from uuid import uuid4
from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class McpServer(Base):
    __tablename__ = "mcp_servers"
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    url: Mapped[str] = mapped_column(String(512))
    auth_type: Mapped[str] = mapped_column(String(16), default="none")
    default_risk: Mapped[str] = mapped_column(String(16), default="medium")  # 任务 38.6：服务级默认风险
    config: Mapped[dict] = mapped_column(JSONB, default=dict)  # 含 tool_risks（任务 38.6）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AgentMcpBinding(Base):
    """Agent 与 MCP 服务的多对多绑定关系。"""
    __tablename__ = "agent_mcp_bindings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    agent_code: Mapped[str] = mapped_column(String(32), index=True)
    mcp_server_name: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)