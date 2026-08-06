# backend/tests/test_chat_api.py
import pytest
from langchain_core.messages import AIMessage
from httpx import AsyncClient, ASGITransport
from app.main import app


class FakeLLM:
    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        if len(messages) == 2:
            return AIMessage(content="", tool_calls=[{
                "name": "query_marketing_campaigns", "args": {"status": "active"}, "id": "c1", "type": "tool_call",
            }])
        return AIMessage(content="营销方案已生成")


@pytest.mark.asyncio
async def test_chat_sse_streams(monkeypatch):
    """SSE 流式：一次营销路由 + done 终止。"""
    decisions = iter([
        {"agent": "marketing", "reason": "营销策划", "confidence": 0.9},
        {"agent": "done", "reason": "任务完成", "confidence": 0.95},
    ])
    async def fake_route(message, agents):
        return next(decisions)
    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)
    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda k: FakeLLM())
    # 记忆装配与后处理 stub，避免真实 embedding/LLM 调用
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
    monkeypatch.setattr("app.services.chat_service.maybe_extract_batch", _extract)
    monkeypatch.setattr("app.services.chat_service.distill_experience", _distill)
    monkeypatch.setattr("app.services.chat_service.generate_title", _title)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "dave", "password": "x123456", "display_name": "Dave"})
        r = await c.post("/api/auth/login", json={"username": "dave", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/conversations", json={}, headers=h)
        conv_id = r.json()["id"]
        r = await c.post("/api/chat/completions",
                         json={"conversation_id": conv_id, "message": "你好"},
                         headers=h)
        assert r.status_code == 200
        assert "data:" in r.text
