# backend/app/tools/loader.py —— 统一工具加载器
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.facade import facade, Tool
from app.tools.mcp_adapter import mcp_registry, get_mcp_tools
from app.tools.risk import get_mcp_risk

logger = logging.getLogger(__name__)

# MCP 工具单次执行限时。外部 MCP 网关（天气/地图等第三方服务）无响应时，工具调用会
# 无限挂起：SSE 流不结束、前端一直转圈、trace 保持 running（真实事故：营销 agent 在
# ReAct 循环里调 mcp_map 天气工具，外部服务无响应挂起 >5min）。发现工具已有 10s 超时，
# 但执行本身没有——这里给执行包 wait_for：超时抛 asyncio.TimeoutError → ToolNode 记为
# 工具错误 → 卡片标 error，agent 继续生成而非挂死（与 stream_llm 超时降级同模式）。
MCP_TOOL_EXEC_TIMEOUT = 20.0


def _with_exec_timeout(fn, timeout: float = MCP_TOOL_EXEC_TIMEOUT):
    """给工具执行包 asyncio.wait_for 超时，外部网关无响应时不再无限等待。

    MCP 工具可执行对象可能是 async（coroutine）或 sync（func）：async 用 wait_for
    包裹，超时取消并抛 TimeoutError；sync 直接调用。"""

    async def wrapped(*args, **kwargs):
        coro = fn(*args, **kwargs)
        if hasattr(coro, "__await__"):
            return await asyncio.wait_for(coro, timeout=timeout)
        return coro

    return wrapped


async def load_mcp_tools_with_risk(db: AsyncSession, server_name: str) -> list[Tool]:
    """连接 MCP 服务发现工具，注入风险等级，包装为 DataFacade.Tool。
    - 风险来源：get_mcp_risk(tool_name, server.default_risk, server.config)
    - 工具名加前缀 mcp_{server_name}_ 防与内置工具重名"""
    from app.repositories.config_repo import McpServerRepository

    # 1. 服务未注册则跳过
    if server_name not in mcp_registry.list():
        return []

    # 2. 查数据库获取风险配置
    mcp_repo = McpServerRepository(db)
    server = await mcp_repo.get_by(name=server_name)
    if not server or not server.enabled:
        return []

    # 3. 连接 MCP 服务，发现所有工具（返回 LangChain Tool 列表）
    try:
        # 加显式超时：不可达/域名解析慢的 MCP 服务不应拖住应用启动
        raw_tools = await asyncio.wait_for(get_mcp_tools(server_name), timeout=10)
    except Exception as e:
        # 单个 MCP 服务不可达不应拖垮整个应用启动/图构建，跳过并告警
        logger.warning("连接 MCP 服务 %s 失败，已跳过其工具: %s", server_name, e)
        return []

    # 4. 注入 risk，包装为 DataFacade.Tool
    result = []
    for t in raw_tools:
        risk = get_mcp_risk(t.name, server.default_risk, server.config)
        # langchain-mcp-adapters 0.3.x 的 MCP 工具可执行对象在 coroutine（异步）/ func（同步）上
        callable_fn = getattr(t, "coroutine", None) or getattr(t, "func", None)
        result.append(Tool(
            name=f"mcp_{server_name}_{t.name}",
            fn=_with_exec_timeout(callable_fn),
            risk=risk,
            description=t.description,
            args_schema=t.args_schema,
        ))
    return result


async def load_tools(db: AsyncSession, builtin_names: list[str], mcp_server_names: list[str]) -> list:
    """统一加载内置工具 + MCP 工具，返回 LangChain Tool 列表。
    - 内置工具：risk 在注册时硬编码声明（facade.get_risk）
    - MCP 工具：risk 从数据库 default_risk + config.tool_risks 动态注入
    各子 agent 构建子图时调用。"""
    # 1. 内置工具（从 facade 单例获取，risk 已硬编码）
    tools = [facade.to_langchain_tool(n) for n in builtin_names]
    # 2. MCP 工具（动态发现 + 注入 risk）
    for server_name in mcp_server_names:
        mcp_tools = await load_mcp_tools_with_risk(db, server_name)
        # MCP 工具未注册进 facade 注册表，直接按 Tool 对象转换
        tools.extend([facade.to_langchain_tool_from(t) for t in mcp_tools])
    return tools


async def load_mcp_tools_by_agent(db: AsyncSession, agent_code: str) -> list[str]:
    """从数据库读取 agent 的 MCP 绑定，返回已启用的 MCP 服务名列表。
    agent 模块用此列表替代硬编码的 MCP_SERVER_NAMES。"""
    from app.repositories.config_repo import AgentMcpBindingRepository
    repo = AgentMcpBindingRepository(db)
    bindings = await repo.list_by_agent(agent_code)
    return [b.mcp_server_name for b in bindings if b.enabled]
