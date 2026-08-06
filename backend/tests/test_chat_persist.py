# backend/tests/test_chat_persist.py
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.models.chat import Message


class FakeLLM:
    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return AIMessage(content="营销方案已生成")


@pytest.mark.asyncio
async def test_messages_persisted_after_chat(db_session, monkeypatch):
    """聊天完成后 user + assistant 消息落库。"""
    async def fake_route(message, agents):
        return {"agent": "marketing", "reason": "r", "confidence": 0.9}
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
    async def _title(msg):
        return "测试标题"
    monkeypatch.setattr("app.memory.assembly.short_term.build_context", _ctx)
    monkeypatch.setattr("app.memory.assembly.pref_mem.build_context", _pref)
    monkeypatch.setattr("app.memory.assembly.exp_mem.build_experience_context", _exp)
    monkeypatch.setattr("app.memory.assembly.knowledge.retrieve_knowledge", _kb)
    monkeypatch.setattr("app.services.chat_service.extract_and_save", _extract)
    monkeypatch.setattr("app.services.chat_service.distill_experience", _distill)
    monkeypatch.setattr("app.services.chat_service.generate_title", _title)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "erin", "password": "x123456", "display_name": "Erin"})
        r = await c.post("/api/auth/login", json={"username": "erin", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/conversations", json={}, headers=h)
        conv_id = r.json()["id"]
        await c.post("/api/chat/completions", json={"conversation_id": conv_id, "message": "hello"}, headers=h)
    msgs = (await db_session.scalars(select(Message))).all()
    assert len(msgs) == 2  # user + assistant
