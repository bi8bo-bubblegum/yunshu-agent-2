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


@pytest.mark.asyncio
async def test_batch_preference_across_conversations(db_session, monkeypatch):
    """偏好按用户跨会话累计：满10条触发；其他用户的消息不计入；对话按会话内配对。"""
    from app.models.chat import Conversation, Message
    from app.services.preference_svc import maybe_extract_batch

    conv1 = Conversation(user_id="u1", title="c1")
    conv2 = Conversation(user_id="u1", title="c2")
    conv_other = Conversation(user_id="u9", title="other")
    db_session.add_all([conv1, conv2, conv_other])
    await db_session.commit()

    calls = []
    async def fake_extract(dialogs):
        calls.append(dialogs)
        return []
    monkeypatch.setattr("app.services.preference_svc.extract_preferences_from_dialogs", fake_extract)

    # u1：conv1 6 轮 + conv2 4 轮 = 10 条用户消息；u9 10 轮（不计入 u1）
    for i in range(6):
        db_session.add(Message(conversation_id=conv1.id, role="user", content=f"c1q{i}"))
        db_session.add(Message(conversation_id=conv1.id, role="assistant", content=f"c1a{i}"))
    for i in range(4):
        db_session.add(Message(conversation_id=conv2.id, role="user", content=f"c2q{i}"))
        db_session.add(Message(conversation_id=conv2.id, role="assistant", content=f"c2a{i}"))
    for i in range(10):
        db_session.add(Message(conversation_id=conv_other.id, role="user", content=f"oq{i}"))
        db_session.add(Message(conversation_id=conv_other.id, role="assistant", content=f"oa{i}"))
    await db_session.commit()

    await maybe_extract_batch(db_session, "u1", conv1.id)
    assert len(calls) == 1
    dialogs = calls[0]
    assert len(dialogs) == 10
    assert sum("c1q" in d for d in dialogs) == 6
    assert sum("c2q" in d for d in dialogs) == 4
    assert all("助手：" in d for d in dialogs)


@pytest.mark.asyncio
async def test_merge_refresh_updated_at(db_session):
    """merge 命中同一偏好时刷新 updated_at：再次观察到该偏好 = 偏好仍活跃。

    关键场景：confidence 不变时 SQLAlchemy 不生成 UPDATE（onupdate 不触发），
    必须显式赋值 updated_at，否则偏好新鲜度永不更新、注入排序恒为 created_at 序。"""
    from datetime import datetime, timezone
    repo = PreferenceRepository(db_session)
    await repo.merge(user_id="u1", category="style", content="回答简洁", confidence=0.8, source="s1")
    row = (await db_session.scalars(select(Preference).where(Preference.user_id == "u1"))).one()
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    row.updated_at = past  # 模拟很久没再确认
    await db_session.flush()
    # 再次确认同一偏好，confidence 相同（仅靠 onupdate 不会刷新）
    await repo.merge(user_id="u1", category="style", content="回答简洁", confidence=0.8, source="s2")
    await db_session.flush()
    assert row.updated_at > past


@pytest.mark.asyncio
async def test_build_context_top_n(db_session):
    """偏好超过注入上限时只取最新 Top-N（LIMIT 截断），最旧偏好被排除。"""
    from datetime import datetime, timedelta, timezone
    from app.memory.preferences import build_context, MAX_PREF_CHARS
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    repo = PreferenceRepository(db_session)
    for i in range(12):
        await repo.merge(user_id="u1", category="style", content=f"偏好{i:02d}", confidence=0.5, source="s")
        row = (await db_session.scalars(select(Preference).where(Preference.user_id == "u1", Preference.content == f"偏好{i:02d}"))).one()
        row.updated_at = base + timedelta(days=i)  # i 越大越新
    await db_session.flush()

    ctx = await build_context(db_session, "u1")
    assert ctx.startswith("【个人偏好】")
    assert "偏好00" not in ctx and "偏好01" not in ctx, "最旧 2 条应被 LIMIT 排除"
    for i in range(2, 12):
        assert f"偏好{i:02d}" in ctx, f"最新偏好{i:02d} 应注入"
    assert len(ctx) <= MAX_PREF_CHARS


@pytest.mark.asyncio
async def test_build_context_recency(db_session):
    """再次确认的偏好 updated_at 刷新后，注入排序前移（软性演化，零误删）。"""
    from datetime import datetime, timezone
    from app.memory.preferences import build_context
    repo = PreferenceRepository(db_session)
    await repo.merge(user_id="u1", category="style", content="回答简洁", confidence=0.6, source="s1")
    await repo.merge(user_id="u1", category="habit", content="偏好邮件沟通", confidence=0.6, source="s1")
    rows = {p.content: p for p in (await db_session.scalars(select(Preference).where(Preference.user_id == "u1"))).all()}
    rows["回答简洁"].updated_at = datetime(2022, 1, 1, tzinfo=timezone.utc)
    rows["偏好邮件沟通"].updated_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    await db_session.flush()

    def _first(ctx: str) -> str:
        return "回答简洁" if ctx.index("回答简洁") < ctx.index("偏好邮件沟通") else "偏好邮件沟通"

    # 新确认的「偏好邮件沟通」优先注入
    assert _first(await build_context(db_session, "u1")) == "偏好邮件沟通"
    # 再次确认「回答简洁」（刷新 updated_at 为当前时间）→ 排到最前
    await repo.merge(user_id="u1", category="style", content="回答简洁", confidence=0.6, source="s2")
    await db_session.flush()
    assert _first(await build_context(db_session, "u1")) == "回答简洁"
