# backend/app/agents/graph.py —— 主图：Supervisor 多轮循环 + checkpointer 持久化
import asyncio

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import BaseMessage, RemoveMessage
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
MAX_MESSAGES = 100   # 图内消息超过该长度触发裁剪（必须晚于滚动摘要生成轮次，见 done_node 注释）
RETAIN_MESSAGES = 60  # 裁剪后保留的消息条数（窗口内完整消息 + 滚动摘要兜底窗口外）


def _trim_messages(msgs: list[BaseMessage], max_len: int = MAX_MESSAGES,
                   retain: int = RETAIN_MESSAGES) -> list[RemoveMessage]:
    """超长消息列表 → 删除窗口外消息的 RemoveMessage 列表；未超长返回空列表。

    messages 通道已改为 add_messages（自动为无 id 消息分配 id），RemoveMessage
    按 id 删除窗口外消息，checkpointer 持久化裁剪后的状态，下一轮只带窗口内消息。"""
    if len(msgs) <= max_len:
        return []
    return [RemoveMessage(id=m.id) for m in msgs[: len(msgs) - retain] if m.id]

_graph: object = None  # 懒初始化单例
_build_lock: asyncio.Lock | None = None
_bg_close_tasks: set[asyncio.Task] = set()  # 持有引用，防 GC 提前取消


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

    checkpoint 管理：子图（compile(checkpointer=True) 的编译图）在固定
    checkpoint_ns 下持久化历史，而 messages 是 add 追加通道——若子图
    直接继承父图 thread_id 累积历史，会与父图每次传入的完整 messages
    用 add 合并重复，导致消息逐轮膨胀、agent 复读用户消息。
    因此子图每次在「父图当前 checkpoint id 派生的独立 sub-thread」上执行：
    从空 checkpoint 全新开始（父图传入的完整 messages 即上下文），
    不叠加子图历史。interrupt 挂起时父图与子图在同一 checkpoint 写快照，
    resume 恢复同一 checkpoint → 派生相同 sub-thread → 子图从挂起点继续。
    非子图节点（普通 callable，如单元测试中的 lambda）原样使用。"""
    if not hasattr(subgraph, "ainvoke"):
        return subgraph

    async def wrapped(state: AgentState, config: RunnableConfig) -> dict:
        input_msgs = list(state.get("messages", []))
        input_rounds = state.get("tool_rounds", 0)
        cfg = (config or {}).get("configurable", {}) or {}
        # 父图当前 checkpoint id：LangGraph 任务 config 里 checkpoint_map
        # 记录了 parent_ns → 当前 checkpoint id（根图 parent_ns 为 ''）。
        parent_cp = ""
        cmap = cfg.get("checkpoint_map") or {}
        for v in cmap.values():
            parent_cp = v
        thread_id = cfg.get("thread_id", "")
        # 派生独立 sub-thread：每次父图 checkpoint 变更 → 新 sub-thread，
        # 子图从空 checkpoint 全新开始，不累积历史。
        sub_config = {"configurable": {**cfg, "thread_id": f"{thread_id}__{parent_cp}"}}
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
        # 取最后一条有实质内容的 assistant 文本输出作为"上一轮 agent 输出"。
        # 不能直接用 msgs[-1]：它可能是工具调用消息（content 为空）、工具结果、
        # 或用户消息，用这些做路由上下文会让 supervisor 误判、复读用户输入。
        for m in reversed(msgs):
            c = m.content if hasattr(m, "content") else ""
            if isinstance(c, list):
                c = "".join(str(b.get("text", "")) for b in c
                            if isinstance(b, dict) and b.get("type") == "text")
            if getattr(m, "type", "") == "ai" and c:
                context += f"\n\n上一轮 agent 输出：{c}"
                break
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
        # 只取最近一条有实质内容的 assistant 文本输出。
        # 必须过滤消息类型：用户消息（HumanMessage）与工具结果（ToolMessage）的
        # content 非空，若不加类型判断会被误当作最终回复，导致 agent 复读用户
        # 消息 / 复读工具结果（真实事故：route_history 满时 router 强制 done、
        # 本轮 agent 未执行，messages 最后一条恰好是用户消息）。
        text = ""
        for m in reversed(msgs):
            if getattr(m, "type", "") != "ai":
                continue
            c = m.content if hasattr(m, "content") else ""
            if isinstance(c, list):
                c = "".join(str(b.get("text", "")) for b in c
                            if isinstance(b, dict) and b.get("type") == "text")
            if c:
                text = c
                break
        # 超长消息裁剪：messages 通道长期只增不减，长对话 token 无限膨胀。
        # 裁剪依赖滚动摘要兜底窗口外内容：chat_service 收尾时 maybe_roll_summary
        # 在 DB 消息满 20 条（约 10 轮）即生成 conv.summary，并经 memory 装配注入；
        # 而 MAX_MESSAGES=100 对应至少 13~50 轮，裁剪必然发生在摘要已生成之后。
        removals = _trim_messages(msgs)
        # 回退到 agent 节点直接写入的 agent_response（对齐文档 5236 行）
        out = {"agent_response": text or state.get("agent_response", "") or "已完成"}
        if removals:
            out["messages"] = removals  # add_messages 按 id 删除窗口外消息
        return out

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
    if _graph is not None:
        return _graph
    global _build_lock
    if _build_lock is None:
        _build_lock = asyncio.Lock()
    async with _build_lock:
        if _graph is None:  # 双检：多个协程同时触发时只构建一次
            async with SessionLocal() as db:
                reg = await _build_registry(db)
            cp = _make_checkpointer()
            await cp.setup()
            _graph = build_graph(reg, cp)
    return _graph


def invalidate_graph() -> None:
    """配置变更（MCP 服务/绑定/风险/认证）后失效缓存主图。
    下一次对话经 get_graph() 懒重建，无需重启；旧图连接池延迟关闭。"""
    global _graph
    old = _graph
    _graph = None
    if old is None:
        return
    checkpointer = getattr(old, "checkpointer", None)
    pool = getattr(checkpointer, "pool", None) if checkpointer is not None else None
    if pool is None:
        return

    async def _close_later():
        # 给可能仍在执行的对话留出收尾时间，再关闭旧连接池
        await asyncio.sleep(300)
        try:
            await pool.close()
        except Exception:
            pass

    task = asyncio.create_task(_close_later())
    _bg_close_tasks.add(task)
    task.add_done_callback(_bg_close_tasks.discard)


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
