# backend/app/agents/graph.py —— 主图：Supervisor 多轮循环 + checkpointer 持久化
import asyncio

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from app.agents.state import AgentState
from app.agents.registry import AgentRegistry
from app.agents.supervisor import route_decision
from app.agents.marketing.agent import build_marketing_agent
from app.agents.sales_analysis.agent import build_sales_agent
from app.agents.scheduling.agent import build_scheduling_agent
from app.core.config import settings
from app.core.database import SessionLocal
from app.tools.facade import facade
from app.tools.builtin import register_builtin_tools

# 模块加载时注册内置工具到 facade 单例
register_builtin_tools(facade)

MAX_ROUTES = 4  # 循环上限，防死循环

_graph: object = None  # 懒初始化单例


async def _build_registry(db) -> AgentRegistry:
    """异步构建注册中心：从数据库加载各 agent 的 MCP 绑定并构建子图。"""
    registry = AgentRegistry()
    registry.register("marketing", await build_marketing_agent(db))
    registry.register("sales_analysis", await build_sales_agent(db))
    registry.register("scheduling", await build_scheduling_agent(db))
    return registry


def build_graph(registry: AgentRegistry):
    """根据已构建的注册中心装配主图。

    流程：supervisor(意图识别) → agent(执行) → supervisor(再判断) → ... → done
    agent 完成后回到 supervisor，由 supervisor 决定是否继续路由其他 agent 或结束。
    """
    g = StateGraph(AgentState)

    async def supervisor_node(state: AgentState) -> dict:
        agents_with_done = registry.list() + ["done"]
        context = state.get("user_message", "")
        msgs = state.get("messages", [])
        if msgs:
            last_msg = msgs[-1].content if hasattr(msgs[-1], "content") else str(msgs[-1])
            context += f"\n\n上一轮 agent 输出：{last_msg}"
        decision = await route_decision(context, agents_with_done)
        return {"pending_agent": decision["agent"], "route_history": [decision["agent"]]}

    def router(state: AgentState) -> str:
        agent = state.get("pending_agent", "done")
        if len(state.get("route_history", [])) >= MAX_ROUTES:
            return "done"
        if agent == "done":
            return "done"
        return agent if agent in registry.list() else "done"

    async def done_node(state: AgentState) -> dict:
        msgs = state.get("messages", [])
        text = msgs[-1].content if msgs else state.get("agent_response", "")
        return {"agent_response": text or "已完成"}

    g.add_node("supervisor", supervisor_node)
    for code in registry.list():
        g.add_node(code, registry.get(code))  # 子图嵌入父图
    g.add_node("done", done_node)
    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", router, {**{c: c for c in registry.list()}, "done": "done"})
    for code in registry.list():
        g.add_edge(code, "supervisor")
    g.add_edge("done", END)

    # 用 checkpointer 编译，thread_id = conversation_id
    pg_url = settings.DATABASE_URL.replace("+asyncpg", "")
    pool = AsyncConnectionPool(pg_url, max_size=10, kwargs={"autocommit": True})
    checkpointer = AsyncPostgresSaver(pool)
    return g.compile(checkpointer=checkpointer)


async def get_graph():
    """懒初始化主图（兼容 pytest-asyncio 无 DB 场景）。"""
    global _graph
    if _graph is None:
        async with SessionLocal() as db:
            reg = await _build_registry(db)
        _graph = build_graph(reg)
    return _graph


# 模块级兼容：同步环境下直接初始化
def _init_sync():
    global _graph
    if _graph is None:
        async def _init():
            async with SessionLocal() as db:
                return await _build_registry(db)
        try:
            loop = asyncio.get_running_loop()
            reg = loop.run_until_complete(_init())
        except RuntimeError:
            reg = asyncio.run(_init())
        _graph = build_graph(reg)


# 尝试同步初始化（仅当有数据库可用时）
try:
    _init_sync()
except Exception:
    pass  # 无数据库时延迟到 get_graph()

# 导出 graph 变量，兼容既有导入
graph = _graph