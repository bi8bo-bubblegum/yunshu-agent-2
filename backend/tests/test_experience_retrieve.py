# backend/tests/test_experience_retrieve.py
import pytest
from datetime import date
from app.models.experience import Experience
from app.memory.experiences import build_experience_context, RELEVANCE_THRESHOLD

@pytest.mark.asyncio
async def test_build_experience_context(db_session, monkeypatch):
    """向量相似度召回：相关经验注入上下文。"""
    db_session.add(Experience(owner_id="u1", scope="personal", status="approved", title="国庆大促",
                              summary="满减+直播", event_time=date(2025, 10, 1), embedding=[0.1] * 1536))
    await db_session.commit()
    # 被 await 的 stub 必须是 async 函数
    async def _embed(t):
        return [0.1] * 1536
    monkeypatch.setattr("app.memory.experiences.embed_query", _embed)
    ctx = await build_experience_context(db_session, user_id="u1", department_id=None, query="国庆营销")
    assert "国庆大促" in ctx


@pytest.mark.asyncio
async def test_low_similarity_experience_not_injected(db_session, monkeypatch):
    """向量相似度低于阈值时，不相关的经验不应注入上下文。"""
    db_session.add(Experience(owner_id="u1", scope="personal", status="approved", title="无关经验",
                              summary="xx", embedding=[0.05] * 1536))
    await db_session.commit()

    async def _embed(t):
        return [0.05] * 1536  # 与查询完全同向量 → 相似度 1.0，但候选分数由 repo 给出
    monkeypatch.setattr("app.memory.experiences.embed_query", _embed)

    # 让 repo 的 vector_search 返回低相似度分数（< 阈值）
    from app.repositories.experience_repo import ExperienceRepository
    async def _vs(self, q, limit=30):
        return [(exp, 0.05) for exp in (await ExperienceRepository(db_session).list_visible("u1", None))]
    monkeypatch.setattr(ExperienceRepository, "vector_search", _vs)

    ctx = await build_experience_context(db_session, user_id="u1", department_id=None, query="编程问题")
    assert ctx == ""


@pytest.mark.asyncio
async def test_same_month_bonus_only_for_relevant(db_session, monkeypatch):
    """同期加权不应用于低于阈值的无关经验。"""
    db_session.add(Experience(owner_id="u1", scope="personal", status="approved", title="无关同期",
                              summary="xx", event_time=date(2024, 1, 1), embedding=[0.1] * 1536))
    await db_session.commit()

    async def _embed(t):
        return [0.1] * 1536
    monkeypatch.setattr("app.memory.experiences.embed_query", _embed)
    # 候选相似度 0.1（低于阈值 0.18）：同期加权只对已相关经验生效，低于阈值的不得被抬进上下文
    from app.repositories.experience_repo import ExperienceRepository
    async def _vs(self, q, limit=30):
        return [(exp, 0.1) for exp in (await ExperienceRepository(db_session).list_visible("u1", None))]
    monkeypatch.setattr(ExperienceRepository, "vector_search", _vs)
    monkeypatch.setattr("app.memory.experiences.datetime", type("DT", (), {"now": staticmethod(lambda: type("N", (), {"month": 1})())}))

    ctx = await build_experience_context(db_session, user_id="u1", department_id=None, query="编程问题")
    assert ctx == ""


@pytest.mark.asyncio
async def test_top_k_returns_most_similar(db_session, monkeypatch):
    """向量相似度排序：top_k 只取相似度最高的候选。"""
    db_session.add(Experience(owner_id="u1", scope="personal", status="approved", title="经验A",
                              summary="a", embedding=[0.1] * 1536))
    db_session.add(Experience(owner_id="u1", scope="personal", status="approved", title="经验B",
                              summary="b", embedding=[0.1] * 1536))
    await db_session.commit()

    async def _embed(t):
        return [0.1] * 1536
    monkeypatch.setattr("app.memory.experiences.embed_query", _embed)
    from app.repositories.experience_repo import ExperienceRepository
    exps = await ExperienceRepository(db_session).list_visible("u1", None)
    async def _vs(self, q, limit=30):
        # A 高分、B 低分：top_k=1 应只选 A
        return [(exps[0], 0.9), (exps[1], 0.2)]
    monkeypatch.setattr(ExperienceRepository, "vector_search", _vs)

    ctx = await build_experience_context(db_session, user_id="u1", department_id=None, query="经验", top_k=1)
    assert "经验A" in ctx
    assert "经验B" not in ctx


@pytest.mark.asyncio
async def test_dept_scope_filtered_by_department(db_session, monkeypatch):
    """dept 范围经验：无 department_id 时不可见，不注入。"""
    db_session.add(Experience(owner_id="u2", scope="dept", status="approved", title="部门经验",
                              summary="s", department_id="dept1", embedding=[0.1] * 1536))
    await db_session.commit()

    async def _embed(t):
        return [0.1] * 1536
    monkeypatch.setattr("app.memory.experiences.embed_query", _embed)
    from app.repositories.experience_repo import ExperienceRepository
    exps = await ExperienceRepository(db_session).list_visible("u1", None)
    async def _vs(self, q, limit=30):
        return [(e, 0.9) for e in exps]
    monkeypatch.setattr(ExperienceRepository, "vector_search", _vs)

    ctx = await build_experience_context(db_session, user_id="u1", department_id=None, query="经验")
    assert "部门经验" not in ctx
