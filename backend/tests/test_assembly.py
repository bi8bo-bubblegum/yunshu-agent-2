# backend/tests/test_assembly.py
import pytest
from app.memory.assembly import assemble_memory

@pytest.mark.asyncio
async def test_assembly_sections(monkeypatch):
    # assembly 内部 await 各记忆模块，stub 必须是 async 函数
    async def _ctx(db, cid, **k):
        return "[短期]"
    async def _pref(db, uid):
        return "[偏好]"
    async def _exp(db, uid, dept, q, **k):
        return "[经验]"
    async def _kb(db, q, **k):
        return "[知识]"
    monkeypatch.setattr("app.memory.assembly.short_term.build_context", _ctx)
    monkeypatch.setattr("app.memory.assembly.pref_mem.build_context", _pref)
    monkeypatch.setattr("app.memory.assembly.exp_mem.build_experience_context", _exp)
    monkeypatch.setattr("app.memory.assembly.knowledge.retrieve_knowledge", _kb)
    ctx = await assemble_memory(None, user_id="u1", conversation_id="c1", department_id="d1", query="国庆营销")
    assert "短期" in ctx and "偏好" in ctx and "经验" in ctx and "知识" in ctx
