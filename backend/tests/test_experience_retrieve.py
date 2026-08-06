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
