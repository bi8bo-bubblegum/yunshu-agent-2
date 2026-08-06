# backend/tests/test_supervisor.py
import pytest
from app.agents.supervisor import route_decision, RouteDecision, ROUTE_SCHEMA

def test_route_schema_fields():
    assert {"agent", "reason", "confidence"} <= set(ROUTE_SCHEMA["properties"].keys())

@pytest.mark.asyncio
async def test_route_decision_parses(monkeypatch):
    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, prompt):
            return RouteDecision(agent="marketing", reason="营销策划", confidence=0.9)
    monkeypatch.setattr("app.agents.supervisor.ModelFactory.get_llm", lambda k: FakeLLM())
    decision = await route_decision("策划国庆营销方案", ["marketing", "sales_analysis", "scheduling", "done"])
    assert decision["agent"] == "marketing"

@pytest.mark.asyncio
async def test_route_decision_done(monkeypatch):
    """验证 supervisor 可返回 done 终止循环。"""
    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, prompt):
            return RouteDecision(agent="done", reason="任务已完成", confidence=0.95)
    monkeypatch.setattr("app.agents.supervisor.ModelFactory.get_llm", lambda k: FakeLLM())
    decision = await route_decision("已完成", ["marketing", "sales_analysis", "scheduling", "done"])
    assert decision["agent"] == "done"
