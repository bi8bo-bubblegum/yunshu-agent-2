# backend/app/repositories/experience_repo.py
from sqlalchemy import select
from sqlalchemy.sql import text as sqltext
from app.models.experience import Experience
from app.repositories.base import BaseRepository

class ExperienceRepository(BaseRepository[Experience]):
    model = Experience

    async def vector_search(self, query_vec: list[float], limit: int = 30) -> list[tuple[Experience, float]]:
        """按向量相似度召回候选经验，返回 (经验对象, 相似度分数)。

        score = 1 - 余弦距离：`embedding <=> :q` 是余弦距离（0 完全一致、越大越远），
        ORDER BY 升序即相似度降序，LIMIT 截断后取前 top_k 即最高相似度候选。
        返回相似度分数供调用方做阈值过滤与排序（service/memory 层不直接执行 SQL）。
        """
        vec_str = "[" + ",".join(map(str, query_vec)) + "]"  # asyncpg 需要字符串形式的向量
        rows = (await self.db.execute(
            sqltext("SELECT id, 1 - (embedding <=> :q) AS score FROM experiences "
                    "WHERE embedding IS NOT NULL ORDER BY embedding <=> :q LIMIT :k"),
            {"q": vec_str, "k": limit},
        )).all()
        result: list[tuple[Experience, float]] = []
        for r in rows:
            obj = await self.get(r.id)
            if obj:
                result.append((obj, float(r.score)))
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