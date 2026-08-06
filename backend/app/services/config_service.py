# backend/app/services/config_service.py
"""配置业务：mcp-server 增查 + agent MCP 绑定 CRUD + 工具风险配置。"""
from fastapi import HTTPException

from app.models.configs import McpServer, AgentMcpBinding
from app.repositories.config_repo import McpServerRepository, AgentMcpBindingRepository
from app.tools.mcp_adapter import mcp_registry


class ConfigService:
    """配置业务：mcp-server 增查；新增 MCP 时同步注册到运行时注册表。"""
    def __init__(self, db):
        self.mcp_repo = McpServerRepository(db)
        self.binding_repo = AgentMcpBindingRepository(db)

    # ---- MCP 服务 CRUD ----

    async def create_mcp(self, name: str, url: str, auth_type: str, default_risk: str = "medium", config: dict | None = None) -> McpServer:
        row = McpServer(name=name, url=url, auth_type=auth_type, default_risk=default_risk, config=config or {})
        await self.mcp_repo.add(row)
        await self.mcp_repo.commit()
        mcp_registry.register({
            "name": row.name, "url": row.url, "auth_type": row.auth_type,
            "config": row.config, "enabled": True,
        })
        return row

    async def list_mcps(self) -> list[McpServer]:
        return await self.mcp_repo.list()

    async def update_tool_risks(self, name: str, tool_risks: dict[str, str]) -> dict:
        """更新 MCP 服务的 config.tool_risks，覆盖特定工具的风险等级。
        config 在注册时为空，由管理员调用本方法写入。"""
        server = await self.mcp_repo.get_by(name=name)
        if not server:
            raise HTTPException(404, "MCP 服务不存在")
        config = server.config or {}
        config["tool_risks"] = tool_risks
        server.config = config
        await self.mcp_repo.commit()
        self._sync_registry(server)
        return {"ok": True, "tool_risks": tool_risks}

    async def update_mcp_auth(self, name: str, auth_type: str, api_key: str | None) -> dict:
        """更新 MCP 服务的认证配置（api_key/bearer 凭证存 config JSONB）。
        修改后经 _sync_registry 同步运行时注册表，get_mcp_tools 组装 Authorization header。"""
        if auth_type not in ("none", "api_key", "bearer"):
            raise HTTPException(400, "auth_type 仅支持 none/api_key/bearer")
        server = await self.mcp_repo.get_by(name=name)
        if not server:
            raise HTTPException(404, "MCP 服务不存在")
        server.auth_type = auth_type
        config = server.config or {}
        if api_key:
            config["api_key"] = api_key
        elif auth_type == "none":
            config.pop("api_key", None)
        server.config = config
        await self.mcp_repo.commit()
        self._sync_registry(server)
        return {"ok": True, "auth_type": auth_type}

    def _sync_registry(self, server: McpServer) -> None:
        """将数据库最新配置同步到运行时注册表（供 get_mcp_tools 读取）。"""
        mcp_registry.register({
            "name": server.name, "url": server.url, "auth_type": server.auth_type,
            "config": server.config, "enabled": server.enabled,
        })

    # ---- Agent MCP 绑定 ----

    async def list_agent_bindings(self, agent_code: str) -> list[AgentMcpBinding]:
        return await self.binding_repo.list_by_agent(agent_code)

    async def add_agent_binding(self, agent_code: str, mcp_server_name: str) -> AgentMcpBinding:
        # 同一 Agent 重复绑定同一 MCP 服务直接拒绝（绑定会在重启后重复加载工具）
        if await self.binding_repo.get_by(agent_code=agent_code, mcp_server_name=mcp_server_name):
            raise HTTPException(409, f"MCP 服务「{mcp_server_name}」已绑定到该 Agent")
        row = AgentMcpBinding(agent_code=agent_code, mcp_server_name=mcp_server_name)
        await self.binding_repo.add(row)
        await self.binding_repo.commit()
        return row

    async def remove_agent_binding(self, binding_id: str) -> None:
        row = await self.binding_repo.get(binding_id)
        if row:
            await self.binding_repo.delete(row)
            await self.binding_repo.commit()