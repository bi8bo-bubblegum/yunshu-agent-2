# backend/app/agents/graph.py —— 主图：Supervisor 多轮循环 + checkpointer 持久化
import asyncio

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph._internal._constants import CONFIG_KEY_CHECKPOINTER
from langchain_core.runnables import RunnableConfig
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
from app.tools.mcp_adapter import load_mcp_servers
from app.traces.collector import collector

# 模块加载时注册内置工具到 facade 单例
register_builtin_tools(facade)

MAX_ROUTES = 4  # 循环上限，防死循环

_graph: object = None  # 懒初始化单例


async def _build_registry(db) -> AgentRegistry:
    """异步构建注册中心：从数据库加载各 agent 的 MCP 绑定并构建子图。
    子图以 checkpointer=True 编译：作为父图节点时继承父图 checkpointer（wrap_subgraph 注入），
    使子图内 interrupt（high/critical 工具）正常工作。"""
    # 将数据库中已启用的 MCP 服务加载进运行时注册表，否则应用重启后
    # mcp_registry 为空，绑定在 agent 上的 MCP 工具会被 loader 静默跳过。
    await load_mcp_servers(db)
    registry = AgentRegistry()
    registry.register("marketing", await build_marketing_agent(db, enable_checkpointer=True))
    registry.register("sales_analysis", await build_sales_agent(db, enable_checkpointer=True))
    registry.register("scheduling", await build_scheduling_agent(db, enable_checkpointer=True))
    return registry


def _make_checkpointer():
    """创建 Postgres 持久化 checkpointer（连接池惰性连接）。"""
    pg_url = settings.DATABASE_URL.replace("+asyncpg", "")
    pool = AsyncConnectionPool(pg_url, max_size=10, kwargs={"autocommit": True})
    return AsyncPostgresSaver(pool)


def wrap_subgraph(subgraph, checkpointer):
    """包装嵌入父图的子图节点，只回传子图新增的增量状态。

    LangGraph 子图作为父图节点时，返回的是子图完整 state 快照
    （包含从父图继承的历史 messages / route_history / tool_rounds）。
    父图对同名 channel 再次应用 add reducer 会重复累积。
    包装后仅将子图真正新增的部分传回父图，避免消息与路由历史膨胀。

    config 处理：给子图传入独立 thread_id + 显式 checkpointer，
    - 独立 thread：子图不会读到父图 checkpoint（避免从父图历史恢复挂起）
    - 显式 checkpointer：子图拥有持久化能力，子图内 interrupt（high/critical 工具）正常工作
    非子图节点（普通 callable，如单元测试中的 lambda）原样使用。"""
    if not hasattr(subgraph, "ainvoke"):
        return subgraph

    async def wrapped(state: AgentState, config: RunnableConfig) -> dict:
        input_msgs = list(state.get("messages", []))
        input_rounds = state.get("tool_rounds", 0)
        cfg = (config or {}).get("configurable", {}) or {}
        parent_thread = cfg.get("thread_id", "default")
        sub_config = {"configurable": {
            **cfg,
            "thread_id": f"{parent_thread}__sub",
            CONFIG_KEY_CHECKPOINTER: checkpointer,
        }}
        result = await subgraph.ainvoke(state, config=sub_config)
        out: dict = {}
        msgs = result.get("messages", [])
        if len(msgs) > len(input_msgs):
            out["messages"] = msgs[len(input_msgs):]
        rounds = result.get("tool_rounds", 0) - input_rounds
        if rounds:
            out["tool_rounds"] = rounds
        if "__interrupt__" in result:
            out["__interrupt__"] = result["__interrupt__"]
        return out
    return wrapped


def build_graph(registry: AgentRegistry, checkpointer=None):
    """根据已构建的注册中心装配主图。

    流程：supervisor(意图识别) → agent(执行) → supervisor(再判断) → ... → done
    agent 完成后回到 supervisor，由 supervisor 决定是否继续路由其他 agent 或结束。
    子图节点经 wrap_subgraph 包装，仅回传增量状态，避免消息重复累积。
    checkpointer 为空时不启用持久化（兼容无 DB 的单元测试场景）。"""
    g = StateGraph(AgentState)

    async def supervisor_node(state: AgentState, config: RunnableConfig = None) -> dict:
        agents_with_done = registry.list() + ["done"]
        context = state.get("user_message", "")
        msgs = state.get("messages", [])
        if msgs:
            last_msg = msgs[-1].content if hasattr(msgs[-1], "content") else str(msgs[-1])
            context += f"\n\n上一轮 agent 输出：{last_msg}"
        decision = await route_decision(context, agents_with_done)
        # 每次路由决策即时留痕（interrupt 挂起时也能看到完整路由轨迹）
        trace_id = state.get("trace_id")
        if trace_id:
            collector.emit(trace_id, "route", {
                "agent": decision["agent"],
                "reason": decision.get("reason", ""),
                "confidence": decision.get("confidence"),
            })
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
        # 取最近一条有实质内容的 agent 输出（最后一条可能是空 content 的工具调用消息）
        text = ""
        for m in reversed(msgs):
            c = m.content if hasattr(m, "content") else str(m)
            if c:
                text = c
                break
        # 回退到 agent 节点直接写入的 agent_response（对齐文档 5236 行）
        return {"agent_response": text or state.get("agent_response", "") or "已完成"}

    g.add_node("supervisor", supervisor_node)
    for code in registry.list():
        g.add_node(code, wrap_subgraph(registry.get(code), checkpointer))  # 子图嵌入父图（增量回传 + 支持 interrupt）
    g.add_node("done", done_node)
    g.set_entry_point("supervisor")
    g.add_conditional_edges("supervisor", router, {**{c: c for c in registry.list()}, "done": "done"})
    for code in registry.list():
        g.add_edge(code, "supervisor")
    g.add_edge("done", END)

    # 用 checkpointer 编译，thread_id = conversation_id
    if checkpointer is None:
        return g.compile()
    return g.compile(checkpointer=checkpointer)


async def get_graph():
    """懒初始化主图（应用事件循环内构建，连接池绑定当前 loop）。
    首次构建时确保 checkpoints 持久化表已建立。"""
    global _graph
    if _graph is None:
        async with SessionLocal() as db:
            reg = await _build_registry(db)
        cp = _make_checkpointer()
        await cp.setup()
        _graph = build_graph(reg, cp)
    return _graph


# 模块级兼容：同步环境下直接初始化（保留供测试等场景调用；
# 应用运行时由 lifespan 在应用事件循环中通过 get_graph() 构建，
# 避免模块导入时用临时事件循环创建数据库连接池导致跨 loop 冲突）
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


# 导出 graph 变量，兼容既有导入；初始为 None，由 get_graph() / lifespan 初始化
graph = _graph
