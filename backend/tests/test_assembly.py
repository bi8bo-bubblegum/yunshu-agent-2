# backend/tests/test_assembly.py
import pytest
from app.memory.assembly import assemble_memory

@pytest.mark.asyncio
async def test_assembly_sections(monkeypatch):
    # assembly 内部 await 各记忆模块，stub 必须是 async 函数
    # 知识库已改 agent 工具（search_knowledge），不再自动装配，故无知识段
    async def _ctx(db, cid, **k):
        return "[短期]"
    async def _pref(db, uid):
        return "[偏好]"
    async def _exp(db, uid, dept, q, **k):
        return "[经验]"
    monkeypatch.setattr("app.memory.assembly.short_term.build_context", _ctx)
    monkeypatch.setattr("app.memory.assembly.pref_mem.build_context", _pref)
    monkeypatch.setattr("app.memory.assembly.exp_mem.build_experience_context", _exp)
    ctx = await assemble_memory(None, user_id="u1", conversation_id="c1", department_id="d1", query="国庆营销")
    assert "短期" in ctx and "偏好" in ctx and "经验" in ctx
    assert "知识" not in ctx  # 知识不再自动装配（改 search_knowledge 工具）
    assert "当前日期：" in ctx
