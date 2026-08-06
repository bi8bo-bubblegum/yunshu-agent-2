# backend/app/services/seed.py —— 种子业务也只走 repo，不直查 DB
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.org import Role
from app.models.configs import AgentMcpBinding
from app.repositories.base import BaseRepository
from app.repositories.config_repo import AgentMcpBindingRepository

class RoleRepository(BaseRepository):
    model = Role

ROLES = [("member", "成员"), ("dept_owner", "部门负责人"), ("admin", "公司管理员")]

async def seed_roles(db: AsyncSession) -> None:
    roles = RoleRepository(db)
    for code, name in ROLES:
        if not await roles.get_by(code=code):
            await roles.add(Role(code=code, name=name))
    await roles.commit()

# 各 agent 默认绑定的 MCP 服务
AGENT_MCP_BINDINGS = [
    ("marketing", "erp"),
    ("sales_analysis", "erp"),
    ("scheduling", "erp"),
]

async def seed_agent_mcp_bindings(db: AsyncSession) -> None:
    """为各 agent 写入默认 MCP 服务绑定（幂等）。"""
    repo = AgentMcpBindingRepository(db)
    for agent_code, mcp_server_name in AGENT_MCP_BINDINGS:
        if not await repo.get_by(agent_code=agent_code, mcp_server_name=mcp_server_name):
            await repo.add(AgentMcpBinding(agent_code=agent_code, mcp_server_name=mcp_server_name))
    await repo.commit()