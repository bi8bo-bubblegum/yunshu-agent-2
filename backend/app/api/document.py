# backend/app/api/documents.py —— 薄路由
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.knowledge_service import KnowledgeService

router = APIRouter(tags=["knowledge"])

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5

def get_knowledge_service(db: AsyncSession = Depends(get_db)) -> KnowledgeService:
    return KnowledgeService(db)

@router.post("/api/documents")
async def upload_document(file: UploadFile = File(...), svc: KnowledgeService = Depends(get_knowledge_service), user: User = Depends(get_current_user)):
    content = await file.read()
    return await svc.upload(user.id, file.filename, content)

@router.get("/api/documents")
async def list_documents(svc: KnowledgeService = Depends(get_knowledge_service), user: User = Depends(get_current_user)):
    return await svc.list(user.id)

@router.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str, svc: KnowledgeService = Depends(get_knowledge_service), user: User = Depends(get_current_user)):
    await svc.delete(user.id, doc_id)
    return {"ok": True}

@router.post("/api/kb/search")
async def search_kb(body: SearchRequest, svc: KnowledgeService = Depends(get_knowledge_service), _: User = Depends(get_current_user)):
    return await svc.search(body.query, body.top_k)