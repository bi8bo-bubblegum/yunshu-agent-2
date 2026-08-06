# backend/tests/test_knowledge_assembly.py
import pytest
from app.memory.knowledge import retrieve_knowledge
from app.memory.knowledge import search_chunks

@pytest.mark.asyncio
async def test_retrieve_knowledge_format(monkeypatch):
    async def fake_search(db, query, k):
        return [{"content": "迟到扣款 50 元", "document_id": "d1", "score": 0.9}]
    monkeypatch.setattr("app.memory.knowledge.search_chunks", fake_search)
    result = await retrieve_knowledge(None, "考勤规则", top_k=3)
    assert "迟到扣款" in result
    assert "d1" in result


@pytest.mark.asyncio
async def test_low_relevance_chunk_not_injected(monkeypatch):
    """rerank 分数低于阈值时，不相关的知识块不应注入。"""
    class _FakeChunkRepo:
        def __init__(self, db):
            self.db = db

        async def vector_search(self, q, top_k=20):
            return [{"id": "c1", "content": "无关内容", "document_id": "d1", "score": 0.9}]

    async def fake_embed(t):
        return [0.1] * 1536
    async def fake_rerank(q, c):
        return [0.05] * len(c)
    monkeypatch.setattr("app.memory.knowledge.embed_query", fake_embed)
    monkeypatch.setattr("app.memory.knowledge.rerank", fake_rerank)
    monkeypatch.setattr("app.memory.knowledge.ChunkRepository", _FakeChunkRepo)

    hits = await search_chunks(None, "编程问题", top_k=5)
    assert hits == []
    assert await retrieve_knowledge(None, "编程问题", top_k=5) == ""
