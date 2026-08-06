# backend/tests/test_knowledge_assembly.py
import pytest
from app.memory.knowledge import retrieve_knowledge

@pytest.mark.asyncio
async def test_retrieve_knowledge_format(monkeypatch):
    async def fake_search(db, query, k):
        return [{"content": "迟到扣款 50 元", "document_id": "d1", "score": 0.9}]
    monkeypatch.setattr("app.memory.knowledge.search_chunks", fake_search)
    result = await retrieve_knowledge(None, "考勤规则", top_k=3)
    assert "迟到扣款" in result
    assert "d1" in result
