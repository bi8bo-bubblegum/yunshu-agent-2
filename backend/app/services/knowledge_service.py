# backend/app/services/knowledge_service.py
import os
from uuid import uuid4
from fastapi import HTTPException
from app.models.knowledge import Document, Chunk
from app.repositories.document_repo import DocumentRepository, ChunkRepository
from app.services.document_parser import parse_text, split_chunks
from app.services.embedding import embed_texts, embed_query

UPLOAD_DIR = "storage/documents"

class KnowledgeService:
    """知识库业务：上传→解析→切分→embedding→入库；语义检索。数据库操作全部委托 repository。"""
    def __init__(self, db):
        self.document_repo = DocumentRepository(db)
        self.chunk_repo = ChunkRepository(db)

    async def upload(self, uploader_id: str, filename: str, content: bytes) -> Document:
        ext = filename.rsplit(".", 1)[-1]
        doc_id = str(uuid4())
        path = os.path.join(UPLOAD_DIR, f"{doc_id}.{ext}")
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)
        doc = Document(id=doc_id, title=filename, file_path=path, status="parsing", uploader_id=uploader_id)
        await self.document_repo.add(doc)
        try:
            text = parse_text(content, ext)
            chunks = split_chunks(text, ext=ext)
            vecs = await embed_texts(chunks)
            await self.chunk_repo.add_all([
                Chunk(document_id=doc_id, seq=i, content=t, embedding=v)
                for i, (t, v) in enumerate(zip(chunks, vecs))
            ])
            doc.status = "ready"
            await self.document_repo.commit()
        except Exception as e:
            doc.status = "failed"
            await self.document_repo.commit()
            raise HTTPException(500, f"解析失败: {e}")
        return doc

    async def search(self, query: str, top_k: int = 5) -> dict:
        query_vec = await embed_query(query)
        return {"results": await self.chunk_repo.vector_search(query_vec, top_k)}

    async def list(self, uploader_id: str) -> list[dict]:
        """文档列表（按上传者）。"""
        rows = await self.document_repo.list_by_user(uploader_id)
        return [{"id": d.id, "title": d.title, "status": d.status,
                 "created_at": d.created_at.isoformat() if d.created_at else None} for d in rows]

    async def delete(self, uploader_id: str, doc_id: str) -> None:
        """删除文档：连带 chunk 与磁盘文件。"""
        doc = await self.document_repo.get(doc_id)
        if not doc or doc.uploader_id != uploader_id:
            raise HTTPException(404, "文档不存在")
        await self.chunk_repo.delete_by_document(doc_id)
        if doc.file_path and os.path.exists(doc.file_path):
            os.remove(doc.file_path)
        await self.document_repo.delete(doc)
        await self.document_repo.commit()