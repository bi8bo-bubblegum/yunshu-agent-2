# backend/tests/test_assembly_in_graph.py
import pytest
from langchain_core.messages import AIMessage
from httpx import AsyncClient, ASGITransport
from app.main import app


class FakeLLM:
    def bind_tools(self, tools):
        return self

    async def ainvoke(self, prompt):
        return AIMessage(content="营销方案已生成")


@pytest.mark.asyncio
async def test_chat_with_memory(monkeypatch):
    decisions = iter([
        {"agent": "marketing", "reason": "r", "confidence": 0.9},
        {"agent": "done", "reason": "完成", "confidence": 0.95},
    ])
    async def fake_route(message, agents):
        return next(decisions)
    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)
    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda k: FakeLLM())
    async def _ctx(db, cid, **k):
        return ""
    async def _pref(db, uid):
        return ""
    async def _exp(db, uid, dept, q, **k):
        return ""
    async def _kb(db, q, **k):
        return ""
    async def _extract(db, uid, text):
        return None
    async def _distill(text, uid, tid):
        return None
    monkeypatch.setattr("app.memory.assembly.short_term.build_context", _ctx)
    monkeypatch.setattr("app.memory.assembly.pref_mem.build_context", _pref)
    monkeypatch.setattr("app.memory.assembly.exp_mem.build_experience_context", _exp)
    monkeypatch.setattr("app.memory.assembly.knowledge.retrieve_knowledge", _kb)
    monkeypatch.setattr("app.services.chat_service.extract_and_save", _extract)
    monkeypatch.setattr("app.services.chat_service.distill_experience", _distill)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "ivan", "password": "x123456", "display_name": "Ivan"})
        r = await c.post("/api/auth/login", json={"username": "ivan", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/conversations", json={}, headers=h)
        conv_id = r.json()["id"]
        r = await c.post("/api/chat/completions", json={"conversation_id": conv_id, "message": "策划国庆营销"}, headers=h)
        assert "营销" in r.text
