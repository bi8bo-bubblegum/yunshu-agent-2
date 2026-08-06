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


@pytest.mark.asyncio
async def test_batch_preference_trigger(db_session, monkeypatch):
    """偏好批量分析：每 10 条用户消息触发一次，且只分析最近一批（增量）。"""
    from app.models.chat import Conversation, Message
    from app.services.preference_svc import maybe_extract_batch

    conv = Conversation(user_id="u1", title="t")
    db_session.add(conv)
    await db_session.commit()

    calls = []
    async def fake_extract(dialogs):
        calls.append(len(dialogs))
        return []
    monkeypatch.setattr("app.services.preference_svc.extract_preferences_from_dialogs", fake_extract)

    # 5 条用户消息：未到批次边界，不触发
    for i in range(5):
        db_session.add(Message(conversation_id=conv.id, role="user", content=f"q{i}"))
        db_session.add(Message(conversation_id=conv.id, role="assistant", content=f"a{i}"))
    await db_session.commit()
    await maybe_extract_batch(db_session, "u1", conv.id)
    assert calls == []

    # 到 10 条：触发一次，分析 10 轮
    for i in range(5):
        db_session.add(Message(conversation_id=conv.id, role="user", content=f"q{i + 5}"))
        db_session.add(Message(conversation_id=conv.id, role="assistant", content=f"a{i + 5}"))
    await db_session.commit()
    await maybe_extract_batch(db_session, "u1", conv.id)
    assert calls == [10]

    # 到 20 条：再触发一次（增量，只分析最近 10 轮）
    for i in range(10):
        db_session.add(Message(conversation_id=conv.id, role="user", content=f"q{i + 10}"))
        db_session.add(Message(conversation_id=conv.id, role="assistant", content=f"a{i + 10}"))
    await db_session.commit()
    await maybe_extract_batch(db_session, "u1", conv.id)
    assert calls == [10, 10]
