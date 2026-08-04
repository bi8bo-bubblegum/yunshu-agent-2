# backend/app/services/embedding.py
from app.llm.factory import ModelFactory

async def embed_texts(texts: list[str]) -> list[list[float]]:
    emb = ModelFactory.get_embedding()
    return await emb.aembed_documents(texts)

async def embed_query(text: str) -> list[float]:
    emb = ModelFactory.get_embedding()
    return await emb.aembed_query(text)