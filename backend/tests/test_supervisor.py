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


class _FailingLLM:
    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, prompt):
        raise ValueError("parse error")


@pytest.mark.asyncio
async def test_route_decision_parse_failure_falls_back_by_keyword(monkeypatch):
    """结构化输出解析失败时，按消息关键词兜底，不得默认 done。"""
    monkeypatch.setattr("app.agents.supervisor.ModelFactory.get_llm", lambda k: _FailingLLM())
    decision = await route_decision("查询一下现在的班次，有没有优化建议",
                                    ["marketing", "sales_analysis", "scheduling", "done"])
    assert decision["agent"] == "scheduling"


class _InvalidCodeLLM:
    def __init__(self, agent: str):
        self.agent = agent

    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, prompt):
        return RouteDecision(agent=self.agent, reason="r", confidence=0.9)


@pytest.mark.asyncio
async def test_route_decision_fuzzy_match(monkeypatch):
    """LLM 返回近似代码（schedule）时模糊匹配到 scheduling。"""
    monkeypatch.setattr("app.agents.supervisor.ModelFactory.get_llm", lambda k: _InvalidCodeLLM("schedule"))
    decision = await route_decision("优化一下班次",
                                    ["marketing", "sales_analysis", "scheduling", "done"])
    assert decision["agent"] == "scheduling"


@pytest.mark.asyncio
async def test_route_decision_invalid_code_no_keyword_done(monkeypatch):
    """LLM 返回无效代码且消息无领域关键词时，兜底为 done。"""
    monkeypatch.setattr("app.agents.supervisor.ModelFactory.get_llm", lambda k: _InvalidCodeLLM("unknown_agent"))
    decision = await route_decision("随便聊聊",
                                    ["marketing", "sales_analysis", "scheduling", "done"])
    assert decision["agent"] == "done"
