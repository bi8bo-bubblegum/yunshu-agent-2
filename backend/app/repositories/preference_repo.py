# backend/app/repositories/preference_repo.py
from datetime import datetime, timezone

from sqlalchemy import select
from app.models.preferences import Preference
from app.repositories.base import BaseRepository

class PreferenceRepository(BaseRepository[Preference]):
    model = Preference

    async def list_by_user(self, user_id: str) -> list[Preference]:
        return list((await self.db.scalars(select(Preference).where(Preference.user_id == user_id))).all())

    async def list_by_user_ranked(self, user_id: str, limit: int) -> list[Preference]:
        """按「新鲜 × confidence」两级排序取 Top-N，供注入预算截断。
        updated_at 优先（最近确认的偏好最相关），同新鲜度按 confidence 降序。"""
        return list((await self.db.scalars(
            select(Preference).where(Preference.user_id == user_id)
            .order_by(Preference.updated_at.desc(), Preference.confidence.desc())
            .limit(limit)
        )).all())

    async def merge(self, user_id: str, category: str, content: str, confidence: float, source: str) -> None:
        """相同 category+content 的偏好合并（取更高 confidence），只 flush 不 commit。
        命中时显式刷新 updated_at：再次观察到该偏好 = 偏好仍活跃，注入排序前移。
        onupdate=func.now() 无法覆盖 confidence 不变（无 UPDATE 生成）的场景，故显式赋值。"""
        existing = (await self.db.scalars(
            select(Preference).where(Preference.user_id == user_id, Preference.category == category, Preference.content == content)
        )).first()
        if existing:
            existing.confidence = max(existing.confidence, confidence)
            existing.updated_at = datetime.now(timezone.utc)
        else:
            self.db.add(Preference(user_id=user_id, category=category, content=content, confidence=confidence, source=source))
        await self.db.flush()