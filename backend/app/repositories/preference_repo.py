# backend/app/repositories/preference_repo.py
from datetime import datetime, timezone

import re
from sqlalchemy import select
from app.models.preferences import Preference
from app.repositories.base import BaseRepository


def _normalize(text: str) -> str:
    """轻量归一化：去空白与常见标点，提高跨轮次匹配率。"""
    return re.sub(r"[\s，。！？、,.!?;；:：\"'“”‘’（）()\-—]+", "", text or "").lower()

class PreferenceRepository(BaseRepository[Preference]):
    model = Preference

    async def list_by_user(self, user_id: str) -> list[Preference]:
        return list((await self.db.scalars(select(Preference).where(Preference.user_id == user_id))).all())

    async def merge(self, user_id: str, category: str, content: str, confidence: float, source: str) -> None:
        """相同类别且内容相近的偏好合并：累计出现次数（证据强度）、更新最后出现时间、取更高 confidence。"""
        rows = (await self.db.scalars(
            select(Preference).where(Preference.user_id == user_id, Preference.category == category)
        )).all()
        existing = next((r for r in rows if _normalize(r.content) == _normalize(content)), None)
        if existing:
            existing.confidence = max(existing.confidence, confidence)
            existing.support_count = (existing.support_count or 1) + 1
            existing.last_seen_at = datetime.now(timezone.utc)
        else:
            self.db.add(Preference(
                user_id=user_id, category=category, content=content, confidence=confidence,
                support_count=1, last_seen_at=datetime.now(timezone.utc), source=source,
            ))
        await self.db.flush()
