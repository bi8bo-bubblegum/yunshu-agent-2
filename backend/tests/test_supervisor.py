# backend/tests/test_supervisor.py
import pytest
from app.agents.supervisor import route_decision, RouteDecision, ROUTE_SCHEMA

def test_route_schema_fields():
    assert {"agent", "reason", "confidence"} <= set(ROUTE_SCHEMA["properties"].keys())

@pytest.mark.asyncio
async def test_route_decision_parses(monkeypatch):
    """系统指令放 SystemMessage、用户内容放 HumanMessage，不得混成一条 user 消息。"""
    captured = {}

    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, prompt):
            captured["prompt"] = prompt
            return RouteDecision(agent="marketing", reason="营销策划", confidence=0.9)
    monkeypatch.setattr("app.agents.supervisor.ModelFactory.get_llm", lambda k: FakeLLM())
    decision = await route_decision("策划国庆营销方案", ["marketing", "sales_analysis", "scheduling", "done"])
    assert decision["agent"] == "marketing"
    # 消息结构：SystemMessage 承载角色/候选/原则，HumanMessage 只承载用户真实输入
    msgs = captured["prompt"]
    assert len(msgs) == 2
    assert msgs[0].type == "system"
    assert "候选 agent" in msgs[0].content and "判断原则" in msgs[0].content
    assert msgs[0].content.count("营销策划 / 活动管理类 → marketing") == 1
    assert msgs[1].type == "human"
    assert msgs[1].content == "策划国庆营销方案"

@pytest.mark.asyncio
async def test_route_decision_lies_done_falls_back(monkeypatch):
    """LLM 返回 done（不应被候选列表接受）时，fuzzy_match 失败后关键词兜底。"""
    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, prompt):
            return RouteDecision(agent="done", reason="任务已完成", confidence=0.95)
    monkeypatch.setattr("app.agents.supervisor.ModelFactory.get_llm", lambda k: FakeLLM())
    decision = await route_decision("帮我做个国庆营销方案", ["marketing", "sales_analysis", "scheduling"])
    # LLM 返回 done，候选列表不含 done → _fuzzy_match 失败 → _infer_agent 兜底到 marketing
    assert decision["agent"] == "marketing"


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
    """LLM 返回无效代码且消息无领域关键词时，关键词兜底仍返回 done。"""
    monkeypatch.setattr("app.agents.supervisor.ModelFactory.get_llm", lambda k: _InvalidCodeLLM("unknown_agent"))
    decision = await route_decision("随便聊聊", ["marketing", "sales_analysis", "scheduling"])
    assert decision["agent"] == "done"
