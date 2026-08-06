# backend/app/repositories/preference_repo.py
from sqlalchemy import select
from app.models.preferences import Preference
from app.repositories.base import BaseRepository

class PreferenceRepository(BaseRepository[Preference]):
    model = Preference

    async def list_by_user(self, user_id: str) -> list[Preference]:
        return list((await self.db.scalars(select(Preference).where(Preference.user_id == user_id))).all())

    async def merge(self, user_id: str, category: str, content: str, confidence: float, source: str) -> None:
        """相同 category+content 的偏好合并（取更高 confidence），只 flush 不 commit。"""
        existing = (await self.db.scalars(
            select(Preference).where(Preference.user_id == user_id, Preference.category == category, Preference.content == content)
        )).first()
        if existing:
            existing.confidence = max(existing.confidence, confidence)
        else:
            self.db.add(Preference(user_id=user_id, category=category, content=content, confidence=confidence, source=source))
        await self.db.flush()