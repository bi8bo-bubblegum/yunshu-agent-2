# backend/app/memory/knowledge.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.document_repo import ChunkRepository
from app.services.embedding import embed_query
from app.services.rerank import rerank

async def search_chunks(db: AsyncSession, query: str, top_k: int = 5) -> list[dict]:
    # 两阶段检索：向量 over-fetch → rerank 精排 → 截断 top_k
    query_vec = await embed_query(query)
    hits = await ChunkRepository(db).vector_search(query_vec, top_k=20)  # over-fetch 20条
    if not hits:
        return []
    texts = [h["content"] for h in hits]
    scores = await rerank(query, texts)  # rerank 精排
    for i, h in enumerate(hits):
        h["score"] = scores[i]
    hits.sort(key=lambda x: -x["score"])
    return [{"id": h["id"], "content": h["content"], "document_id": h["document_id"]} for h in hits[:top_k]]

async def retrieve_knowledge(db: AsyncSession, query: str, top_k: int = 5) -> str:
    hits = await search_chunks(db, query, top_k)
    if not hits:
        return ""
    parts = [f"- [{h['document_id']}] {h['content']}" for h in hits]
    return "【知识库参考】\n" + "\n".join(parts)