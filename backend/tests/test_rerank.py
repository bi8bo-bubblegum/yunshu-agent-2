# backend/tests/test_rerank.py
import pytest
from app.services.rerank import rerank, RerankOutput, RerankItem

@pytest.mark.asyncio
async def test_rerank_returns_scores(monkeypatch):
    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, prompt):
            return RerankOutput(items=[
                RerankItem(score=0.9, reason="高度相关"),
                RerankItem(score=0.3, reason="弱相关"),
            ])
    monkeypatch.setattr("app.services.rerank.ModelFactory.get_llm", lambda: FakeLLM())
    scores = await rerank("国庆营销", ["国庆大促方案", "春节红包活动"])
    assert len(scores) == 2
    assert scores[0] > scores[1]

@pytest.mark.asyncio
async def test_rerank_empty():
    scores = await rerank("test", [])
    assert scores == []
