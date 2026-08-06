# backend/tests/test_documents_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_upload_and_search(monkeypatch):
    # pgvector Vector(1536) 列要求 1536 维；被 await 的 stub 必须是 async 函数
    async def fake_embed(texts):
        return [[0.1] * 1536] * len(texts)
    async def fake_embed_query(t):
        return [0.1] * 1536
    monkeypatch.setattr("app.services.knowledge_service.embed_texts", fake_embed)
    monkeypatch.setattr("app.services.knowledge_service.embed_query", fake_embed_query)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "frank", "password": "x123456", "display_name": "Frank"})
        r = await c.post("/api/auth/login", json={"username": "frank", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        files = {"file": ("制度.md", "# 考勤制度\n迟到扣款 50 元".encode(), "text/markdown")}
        r = await c.post("/api/documents", files=files, headers=h)
        assert r.status_code == 200
        doc_id = r.json()["id"]
        r = await c.post("/api/kb/search", json={"query": "考勤"}, headers=h)
        assert r.status_code == 200
        assert len(r.json()["results"]) >= 1
        assert doc_id is not None
