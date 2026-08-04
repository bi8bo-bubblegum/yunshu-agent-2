from app.models import Document, Chunk
from app.repositories.base import BaseRepository
from sqlalchemy.sql import text as sqltext


class DocumentRepository(BaseRepository[Document]):
    model = Document

class ChunkRepository(BaseRepository[Chunk]):
    model = Chunk

    async def vector_search(self, query_vec: list[float], top_k: int = 5) -> list[dict]:
        """pgvector 相似度检索（service/memory 层不再直接执行 SQL）。"""
        rows = (await self.db.execute(
            sqltext(
                "SELECT id, content, document_id, 1 - (embedding <=> :q) AS score "
                "FROM chunks WHERE embedding IS NOT NULL ORDER BY embedding <=> :q LIMIT :k"
            ),
            {"q": query_vec, "k": top_k},
        )).all()
        return [{"id": r.id, "content": r.content, "document_id": r.document_id, "score": round(r.score, 4)} for r in rows]