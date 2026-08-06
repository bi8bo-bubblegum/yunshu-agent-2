# backend/tests/test_preferences.py
import pytest
from sqlalchemy import select
from app.models.preferences import Preference
from app.repositories.preference_repo import PreferenceRepository

@pytest.mark.asyncio
async def test_merge_dedupe(db_session):
    """相同 category+content 偏好合并，保留更高 confidence。"""
    repo = PreferenceRepository(db_session)
    await repo.merge(user_id="u1", category="style", content="回答简洁", confidence=0.8, source="s1")
    await repo.merge(user_id="u1", category="style", content="回答简洁", confidence=0.9, source="s2")
    await db_session.commit()
    rows = (await db_session.scalars(select(Preference).where(Preference.user_id == "u1"))).all()
    assert len(rows) == 1
    assert rows[0].confidence == 0.9
