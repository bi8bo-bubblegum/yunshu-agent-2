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
    assert result["route_history"] == ["marketing"]  # agent→done 不回 supervisor
