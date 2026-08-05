# backend/app/tools/mcp_adapter.py
"""MCP 服务注册表与动态工具发现。
- MCPRegistry：运行时内存注册表（增删查）
- load_mcp_servers：从数据库加载已启用的 MCP 服务到注册表
- get_mcp_tools：通过 langchain-mcp-adapters 连接远端服务发现工具"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.configs import McpServer


class MCPRegistry:
    def __init__(self):
        self._servers: dict[str, dict] = {}

    def register(self, server: dict) -> None:
        if server.get("enabled", True):
            self._servers[server["name"]] = server

    def unregister(self, name: str) -> None:
        self._servers.pop(name, None)

    def list(self) -> list[str]:
        return list(self._servers.keys())

    def get(self, name: str) -> dict | None:
        return self._servers.get(name)


mcp_registry = MCPRegistry()


async def load_mcp_servers(db: AsyncSession) -> None:
    """从数据库加载所有已启用的 MCP 服务到运行时注册表。"""
    rows = (await db.scalars(select(McpServer))).all()
    for row in rows:
        mcp_registry.register({
            "name": row.name, "url": row.url, "auth_type": row.auth_type,
            "config": row.config, "enabled": row.enabled,
        })


def _build_connection(cfg: dict) -> dict:
    """根据服务配置组装 MultiServerMCPClient 连接参数。
    - auth_type=api_key/bearer 且 config.api_key 存在时，组装 Authorization header
    - 其余（none）不传认证信息"""
    conn: dict = {"url": cfg["url"], "transport": "streamable_http"}
    auth_type = cfg.get("auth_type", "none")
    config = cfg.get("config") or {}
    if auth_type in ("api_key", "bearer") and config.get("api_key"):
        conn["headers"] = {"Authorization": f"Bearer {config['api_key']}"}
    return conn


async def get_mcp_tools(server_name: str) -> list:
    """通过 langchain-mcp-adapters 把远端 MCP 工具转为 LangChain Tool。
    认证：从注册表配置组装 headers（api_key/bearer 凭证存数据库 config JSONB）。"""
    from langchain_mcp_adapters.client import MultiServerMCPClient
    cfg = mcp_registry._servers[server_name]
    client = MultiServerMCPClient({server_name: _build_connection(cfg)})
    return await client.get_tools(server_name)