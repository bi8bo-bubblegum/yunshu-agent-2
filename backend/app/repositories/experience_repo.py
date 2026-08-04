# backend/app/repositories/experience_repo.py
from sqlalchemy.sql import text as sqltext
from app.models.experience import Experience
from app.repositories.base import BaseRepository

class ExperienceRepository(BaseRepository[Experience]):
    model = Experience

    async def vector_search(self, query_vec: list[float], limit: int = 30) -> list[Experience]:
        """按向量相似度召回候选经验（service/memory 层不直接执行 SQL）。"""
        rows = (await self.db.execute(
            sqltext("SELECT id FROM experiences WHERE embedding IS NOT NULL ORDER BY embedding <=> :q LIMIT :k"),
            {"q": query_vec, "k": limit},
        )).all()
        result = []
        for r in rows:
            obj = await self.get(r.id)
            if obj:
                result.append(obj)
        return result