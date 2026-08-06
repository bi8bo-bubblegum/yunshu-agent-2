# backend/tests/test_embedding.py
import pytest
from app.services.embedding import embed_texts

@pytest.mark.asyncio
async def test_embed_texts(monkeypatch):
    monkeypatch.setattr("app.services.embedding.ModelFactory.get_embedding", lambda: FakeEmb())
    vecs = await embed_texts(["hello", "world"])
    assert len(vecs) == 2 and len(vecs[0]) == 3

class FakeEmb:
    async def aembed_documents(self, texts):
        return [[1.0, 0.0, 0.0]] * len(texts)

    async def aembed_query(self, text):
        return [1.0, 0.0, 0.0]
