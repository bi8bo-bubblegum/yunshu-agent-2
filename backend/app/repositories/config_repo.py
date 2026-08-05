# backend/app/repositories/config_repo.py
from app.models.configs import McpServer, AgentMcpBinding
from app.repositories.base import BaseRepository
from sqlalchemy import select


class McpServerRepository(BaseRepository[McpServer]):
    model = McpServer


class AgentMcpBindingRepository(BaseRepository[AgentMcpBinding]):
    model = AgentMcpBinding

    async def list_by_agent(self, agent_code: str) -> list[AgentMcpBinding]:
        return list((await self.db.scalars(
            select(AgentMcpBinding).where(AgentMcpBinding.agent_code == agent_code)
        )).all())