# backend/app/agents/graph.py 重写：Supervisor 多轮循环主图，子 agent 子图作为节点嵌入
import asyncio
from langgraph.graph import StateGraph, END
from app.agents.state import AgentState
from app.agents.registry import AgentRegistry
from app.agents.supervisor import route_decision
from app.agents.marketing.agent import build_marketing_agent
from app.agents.sales_analysis.agent import build_sales_agent
from app.agents.scheduling.agent import build_scheduling_agent

MAX_ROUTES = 4  # 循环上限，防死循环

async def _build_registry() -> AgentRegistry:
    """异步构建注册中心：子 agent 构建时需动态加载 MCP 工具（远端 HTTP 调用）。"""
    registry = AgentRegistry()
    registry.register("marketing", await build_marketing_agent())       # 编译后的子图直接作节点
    registry.register("sales_analysis", await build_sales_agent())
    registry.register("scheduling", await build_scheduling_agent())
    return registry

def build_graph(registry: AgentRegistry):
    """根据已构建的注册中心装配主图。

    流程：supervisor(意图识别) → agent(执行) → supervisor(再判断) → ... → done
    agent 完成后回到 supervisor，由 supervisor 决定是否继续路由其他 agent 或结束。
    """
    g = StateGraph(AgentState)

    async def supervisor_node(state: AgentState) -> dict:
        # 可选列表 = 所有注册的 agent + done（终止循环）
        agents_with_done = registry.list() + ["done"]
        # 拼接上下文：用户消息 + 已有对话历史（供 LLM 判断是否完成）
        context = state.get("user_message", "")
        msgs = state.get("messages", [])
        if msgs:
            last_msg = msgs[-1].content if hasattr(msgs[-1], "content") else str(msgs[-1])
            context += f"\n\n上一轮 agent 输出：{last_msg}"
        decision = await route_decision(context, agents_with_done)
        return {"pending_agent": decision["agent"], "route_history": [decision["agent"]]}

    def router(state: AgentState) -> str:
        agent = state.get("pending_agent", "done")
        # 循环超限 → 强制结束
        if len(state.get("route_history", [])) >= MAX_ROUTES:
            return "done"
        # supervisor 判断 done → 结束
        if agent == "done":
            return "done"
        # 路由到目标 agent
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
    # supervisor → agent 或 done
    g.add_conditional_edges("supervisor", router, {**{c: c for c in registry.list()}, "done": "done"})
    # agent → supervisor（多轮循环：agent 完成后回到 supervisor 再判断）
    for code in registry.list():
        g.add_edge(code, "supervisor")
    g.add_edge("done", END)
    return g.compile()

# 模块级初始化：异步构建注册中心 + 编译主图
registry = asyncio.run(_build_registry())
graph = build_graph(registry)
