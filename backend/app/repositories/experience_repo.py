# backend/app/repositories/experience_repo.py
from sqlalchemy import select
from sqlalchemy.sql import text as sqltext
from app.models.experience import Experience, ExperienceApproval
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

    async def list_visible(self, user_id: str, department_id: str | None) -> list[Experience]:
        """个人层本人 + 部门层同部门 + 公司层全员。"""
        return list((await self.db.scalars(
            select(Experience).where(
                (Experience.owner_id == user_id)
                | (Experience.scope == "company")
                | ((Experience.scope == "dept") & (Experience.department_id == department_id))
            ).order_by(Experience.created_at.desc())
        )).all())

class ApprovalRepository(BaseRepository[ExperienceApproval]):
    model = ExperienceApproval

    async def list_pending(self) -> list[ExperienceApproval]:
        return list((await self.db.scalars(select(ExperienceApproval).where(ExperienceApproval.status == "pending"))).all())