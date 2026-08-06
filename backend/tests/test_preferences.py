# backend/tests/test_preferences.py
import pytest
from sqlalchemy import select
from app.models.preferences import Preference
from app.repositories.preference_repo import PreferenceRepository
from app.memory.preferences import build_context

@pytest.mark.asyncio
async def test_merge_dedupe(db_session):
    """相同偏好合并：保留更高 confidence 并累计出现次数。"""
    repo = PreferenceRepository(db_session)
    await repo.merge(user_id="u1", category="style", content="回答简洁", confidence=0.8, source="s1")
    await repo.merge(user_id="u1", category="style", content="回答简洁", confidence=0.9, source="s2")
    await db_session.commit()
    rows = (await db_session.scalars(select(Preference).where(Preference.user_id == "u1"))).all()
    assert len(rows) == 1
    assert rows[0].confidence == 0.9
    assert rows[0].support_count == 2
    assert rows[0].last_seen_at is not None


@pytest.mark.asyncio
async def test_merge_normalizes_content(db_session):
    """标点/空格差异视为同一偏好，累计出现次数。"""
    repo = PreferenceRepository(db_session)
    await repo.merge(user_id="u2", category="decision", content="预算 50000 元", confidence=0.7, source="s1")
    await repo.merge(user_id="u2", category="decision", content="预算50000元！", confidence=0.8, source="s2")
    await db_session.commit()
    rows = (await db_session.scalars(select(Preference).where(Preference.user_id == "u2"))).all()
    assert len(rows) == 1
    assert rows[0].support_count == 2


@pytest.mark.asyncio
async def test_build_context_only_stable_preferences(db_session):
    """只出现一次的偏好不注入上下文，出现两次及以上才注入。"""
    repo = PreferenceRepository(db_session)
    await repo.merge(user_id="u3", category="style", content="一次性表述", confidence=0.7, source="s1")
    await repo.merge(user_id="u3", category="habit", content="习惯A", confidence=0.7, source="s1")
    await repo.merge(user_id="u3", category="habit", content="习惯A", confidence=0.8, source="s2")
    await db_session.commit()
    ctx = await build_context(db_session, "u3")
    assert "一次性表述" not in ctx
    assert "习惯A" in ctx
    assert "出现2次" in ctx
