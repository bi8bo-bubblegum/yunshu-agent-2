# backend/tests/test_registry.py
import pytest
from app.agents.registry import AgentRegistry

def test_register_and_list():
    reg = AgentRegistry()
    reg.register("marketing", lambda s: {"agent_response": "m"})
    reg.register("sales_analysis", lambda s: {"agent_response": "s"})
    assert set(reg.list()) == {"marketing", "sales_analysis"}

@pytest.mark.asyncio
async def test_multi_round_loop(monkeypatch):
    """验证 supervisor 多轮循环：agent 完成后回到 supervisor，直到 done。"""
    from app.agents.graph import build_graph
    from app.agents.registry import AgentRegistry

    # 模拟 route_decision：先选 marketing，再选 done
    decisions = iter([
        {"agent": "marketing", "reason": "营销分析", "confidence": 0.9},
        {"agent": "done", "reason": "任务完成", "confidence": 0.95},
    ])

    async def fake_route(message, agents):
        return next(decisions)

    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)

    reg = AgentRegistry()
    reg.register("marketing", lambda s: {"agent_response": "营销结果"})
    reg.register("sales_analysis", lambda s: {"agent_response": "分析结果"})

    g = build_graph(reg)
    result = await g.ainvoke({
        "user_message": "帮我做营销分析",
        "pending_agent": "", "route_history": [], "messages": [],
    })
    assert result["agent_response"] == "营销结果"
    assert len(result["route_history"]) == 2  # marketing + done


@pytest.mark.asyncio
async def test_repeat_agent_forced_done(monkeypatch):
    """同一 agent 连续路由时强制 done：LLM 结构化输出偶发自相矛盾
    （reason 说该 done 但 agent 填旧值），连续路由同一 agent 不会产生新工作，
    代码层守卫强制结束避免空转（真实事故：marketing 被路由 4 次直到 MAX_ROUTES）。"""
    from app.agents.graph import build_graph
    from app.agents.registry import AgentRegistry

    # 模拟 route_decision：连续返回 marketing（LLM 自相矛盾场景）
    decisions = iter([
        {"agent": "marketing", "reason": "营销分析", "confidence": 0.9},
        {"agent": "marketing", "reason": "应返回 done 但填了 marketing", "confidence": 0.95},
        {"agent": "marketing", "reason": "第三次", "confidence": 0.9},
    ])

    async def fake_route(message, agents):
        return next(decisions)

    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)

    reg = AgentRegistry()
    reg.register("marketing", lambda s: {"agent_response": "营销结果"})

    g = build_graph(reg)
    result = await g.ainvoke({
        "user_message": "帮我查活动",
        "pending_agent": "", "route_history": [], "messages": [],
    })
    # 守卫触发：marketing → done（第二次 marketing 被改写为 done），不空转
    assert result["agent_response"] == "营销结果"
    assert result["route_history"] == ["marketing", "done"], result["route_history"]
