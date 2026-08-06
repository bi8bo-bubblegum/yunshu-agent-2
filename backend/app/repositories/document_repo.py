from app.models import Document, Chunk
from app.repositories.base import BaseRepository
from sqlalchemy import delete, select
from sqlalchemy.sql import text as sqltext


class DocumentRepository(BaseRepository[Document]):
    model = Document

    async def list_by_user(self, uploader_id: str) -> list[Document]:
        return list((await self.db.scalars(
            select(Document).where(Document.uploader_id == uploader_id)
            .order_by(Document.created_at.desc())
        )).all())

class ChunkRepository(BaseRepository[Chunk]):
    model = Chunk

    async def delete_by_document(self, document_id: str) -> None:
        await self.db.execute(delete(Chunk).where(Chunk.document_id == document_id))

    async def vector_search(self, query_vec: list[float], top_k: int = 5) -> list[dict]:
        """pgvector 相似度检索（service/memory 层不再直接执行 SQL）。"""
        vec_str = "[" + ",".join(map(str, query_vec)) + "]"  # asyncpg 需要字符串形式的向量
        rows = (await self.db.execute(
            sqltext(
                "SELECT id, content, document_id, 1 - (embedding <=> :q) AS score "
                "FROM chunks WHERE embedding IS NOT NULL ORDER BY embedding <=> :q LIMIT :k"
            ),
            {"q": vec_str, "k": top_k},
        )).all()
        return [{"id": r.id, "content": r.content, "document_id": r.document_id, "score": round(r.score, 4)} for r in rows]