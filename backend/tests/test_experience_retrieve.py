# backend/tests/test_experience_retrieve.py
import pytest
from datetime import date
from app.models.experience import Experience
from app.memory.experiences import build_experience_context

@pytest.mark.asyncio
async def test_build_experience_context(db_session, monkeypatch):
    db_session.add(Experience(owner_id="u1", scope="personal", status="approved", title="国庆大促",
                              summary="满减+直播", event_time=date(2025, 10, 1), embedding=[0.1] * 1536))
    await db_session.commit()
    # 被 await 的 stub 必须是 async 函数
    async def _embed(t):
        return [0.1] * 1536
    async def _rerank(q, c):
        return [0.9] * len(c)
    monkeypatch.setattr("app.memory.experiences.embed_query", _embed)
    monkeypatch.setattr("app.memory.experiences.rerank", _rerank)
    ctx = await build_experience_context(db_session, user_id="u1", department_id=None, query="国庆营销")
    assert "国庆大促" in ctx


@pytest.mark.asyncio
async def test_low_relevance_experience_not_injected(db_session, monkeypatch):
    """rerank 分数低于阈值时，不相关的经验不应注入上下文。"""
    db_session.add(Experience(owner_id="u1", scope="personal", status="approved", title="无关经验",
                              summary="xx", embedding=[0.1] * 1536))
    await db_session.commit()

    async def _embed(t):
        return [0.1] * 1536
    async def _rerank(q, c):
        return [0.05] * len(c)
    monkeypatch.setattr("app.memory.experiences.embed_query", _embed)
    monkeypatch.setattr("app.memory.experiences.rerank", _rerank)

    ctx = await build_experience_context(db_session, user_id="u1", department_id=None, query="编程问题")
    assert ctx == ""


@pytest.mark.asyncio
async def test_same_month_bonus_only_for_relevant(db_session, monkeypatch):
    """同期加权不应用于基础分低于阈值的无关经验。"""
    from datetime import date
    db_session.add(Experience(owner_id="u1", scope="personal", status="approved", title="无关同期",
                              summary="xx", event_time=date(2024, 1, 1), embedding=[0.1] * 1536))
    await db_session.commit()

    async def _embed(t):
        return [0.1] * 1536
    async def _rerank(q, c):
        return [0.25] * len(c)  # 低于阈值，即使加 0.1 也不应入选
    monkeypatch.setattr("app.memory.experiences.embed_query", _embed)
    monkeypatch.setattr("app.memory.experiences.rerank", _rerank)
    monkeypatch.setattr("app.memory.experiences.datetime", type("DT", (), {"now": staticmethod(lambda: type("N", (), {"month": 1})())}))

    ctx = await build_experience_context(db_session, user_id="u1", department_id=None, query="编程问题")
    assert ctx == ""


@pytest.mark.asyncio
async def test_rerank_missing_scores_padded(db_session, monkeypatch):
    """rerank 返回数量不足时按 0 分补齐，不抛异常。"""
    db_session.add(Experience(owner_id="u1", scope="personal", status="approved", title="经验A",
                              summary="a", embedding=[0.1] * 1536))
    db_session.add(Experience(owner_id="u1", scope="personal", status="approved", title="经验B",
                              summary="b", embedding=[0.1] * 1536))
    await db_session.commit()

    async def _embed(t):
        return [0.1] * 1536
    async def _rerank(q, c):
        return [0.9]  # 只返回 1 个分数
    monkeypatch.setattr("app.memory.experiences.embed_query", _embed)
    monkeypatch.setattr("app.memory.experiences.rerank", _rerank)

    ctx = await build_experience_context(db_session, user_id="u1", department_id=None, query="经验")
    assert "经验A" in ctx
    assert "经验B" not in ctx
