# backend/app/api/configs.py —— 薄路由：MCP 服务 + Agent MCP 绑定 + 工具风险
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.config_service import ConfigService

router = APIRouter(tags=["configs"])


# ---- Request Schemas ----

class McpIn(BaseModel):
    name: str
    url: str
    auth_type: str = "none"
    config: dict = {}


class AgentMcpBindingIn(BaseModel):
    mcp_server_name: str


class ToolRisksUpdate(BaseModel):
    tool_risks: dict[str, str]  # {"delete_order": "critical", "adjust_schedule": "high"}


def get_config_service(db: AsyncSession = Depends(get_db)) -> ConfigService:
    return ConfigService(db)


# ---- MCP 服务 CRUD ----

@router.post("/api/mcp-servers")
async def create_mcp(body: McpIn,
                     svc: ConfigService = Depends(get_config_service),
                     _: User = Depends(get_current_user)):
    return await svc.create_mcp(body.name, body.url, body.auth_type, body.config)


@router.get("/api/mcp-servers")
async def list_mcp(svc: ConfigService = Depends(get_config_service),
                   _: User = Depends(get_current_user)):
    return await svc.list_mcps()


@router.get("/api/mcp-servers/{name}/tools")
async def list_mcp_tools(name: str,
                         db: AsyncSession = Depends(get_db),
                         _: User = Depends(get_current_user)):
    """连接 MCP 服务，返回已发现的所有工具列表（含当前 risk）。
    供管理员查看后按需通过 tool-risks 接口配置风险等级。"""
    from app.tools.mcp_adapter import mcp_registry, get_mcp_tools
    from app.repositories.config_repo import McpServerRepository
    from app.tools.risk import get_mcp_risk

    if name not in mcp_registry.list():
        raise HTTPException(404, "MCP 服务未注册")

    # 连接 MCP 服务发现工具
    raw_tools = await get_mcp_tools(name)

    # 查风险配置
    mcp_repo = McpServerRepository(db)
    server = await mcp_repo.get(name)

    return [
        {
            "name": t.name,
            "description": t.description,
            "risk": get_mcp_risk(t.name, server.default_risk, server.config),
        }
        for t in raw_tools
    ]


@router.put("/api/mcp-servers/{name}/tool-risks")
async def update_tool_risks(name: str, body: ToolRisksUpdate,
                            svc: ConfigService = Depends(get_config_service),
                            _: User = Depends(get_current_user)):
    """更新 MCP 服务的 config.tool_risks，覆盖特定工具的风险等级。
    管理员先通过 GET .../tools 查看工具清单，再调用本接口配置风险。"""
    return await svc.update_tool_risks(name, body.tool_risks)


# ---- Agent MCP 绑定 ----

@router.get("/api/agents/{agent_code}/mcp-bindings")
async def list_agent_bindings(agent_code: str,
                              svc: ConfigService = Depends(get_config_service),
                              _: User = Depends(get_current_user)):
    return await svc.list_agent_bindings(agent_code)


@router.post("/api/agents/{agent_code}/mcp-bindings")
async def add_agent_binding(agent_code: str, body: AgentMcpBindingIn,
                            svc: ConfigService = Depends(get_config_service),
                            _: User = Depends(get_current_user)):
    return await svc.add_agent_binding(agent_code, body.mcp_server_name)


@router.delete("/api/agents/{agent_code}/mcp-bindings/{binding_id}")
async def remove_agent_binding(agent_code: str, binding_id: str,
                               svc: ConfigService = Depends(get_config_service),
                               _: User = Depends(get_current_user)):
    await svc.remove_agent_binding(binding_id)
    return {"ok": True}