"""回归：流式聊天 + high/critical 多级 interrupt 全链路。

用 FakeLLM 强制触发 create(high) → publish(critical) 工具链，验证：
SSE confirm_required → resume → 审批中心 decide → 图恢复 → 回复落库。
"""
import asyncio
import json
import time

import pytest
from httpx import AsyncClient, ASGITransport
from langchain_core.messages import AIMessage
from sqlalchemy import update

from app.main import app
from app.models.org import User


async def _wait_assistant(c, conv_id, h, timeout=5.0):
    """轮询等待后台图恢复落库 assistant 消息（decide 改后台任务后不再同步等）。"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h)).json()
        assistant = [m for m in msgs if m["role"] == "assistant"]
        if assistant:
            return assistant
        await asyncio.sleep(0.1)
    return []


class SequencedLLM:
    """按调用顺序返回：create 工具调用 → publish 工具调用 → 最终方案。"""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "create_marketing_campaign",
                "args": {"name": "国庆大促", "budget": 50000, "channel": "全渠道",
                         "start_date": "2024-10-01", "end_date": "2024-10-07"},
                "id": "c1", "type": "tool_call",
            }])
        if self.calls == 2:
            return AIMessage(content="", tool_calls=[{
                "name": "publish_campaign",
                "args": {"campaign_id": "C50000", "channels": ["全渠道"]},
                "id": "c2", "type": "tool_call",
            }])
        return AIMessage(content="最终方案已生成")


async def _stubs(monkeypatch):
    async def fake_route(message, agents):
        return {"agent": "marketing", "reason": "r", "confidence": 0.9}
    async def _ctx(db, cid, **k):
        return ""
    async def _pref(db, uid):
        return ""
    async def _exp(db, uid, dept, q, **k):
        return ""
    async def _extract(db, uid, text):
        return None
    async def _distill(text, uid, tid):
        return None
    async def _title(msg):
        return "测试标题"
    async def _save_exp(db, exp):
        return None
    async def _roll(db, cid, **k):
        return None
    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)
    monkeypatch.setattr("app.memory.assembly.short_term.build_context", _ctx)
    monkeypatch.setattr("app.memory.assembly.pref_mem.build_context", _pref)
    monkeypatch.setattr("app.memory.assembly.exp_mem.build_experience_context", _exp)
    monkeypatch.setattr("app.services.chat_service.maybe_extract_batch", _extract)
    monkeypatch.setattr("app.services.chat_service.distill_experience", _distill)
    # 审批恢复路径在函数内按模块导入，需按源模块 stub
    monkeypatch.setattr("app.services.preference_svc.maybe_extract_batch", _extract)
    monkeypatch.setattr("app.services.experience_svc.distill_experience", _distill)
    monkeypatch.setattr("app.services.experience_svc.save_personal_experience", _save_exp)
    monkeypatch.setattr("app.services.summary.maybe_roll_summary", _roll)
    monkeypatch.setattr("app.services.summary.generate_title", _title)


@pytest.mark.asyncio
async def test_critical_approval_flow(db_session, monkeypatch):
    await _stubs(monkeypatch)
    seq = SequencedLLM()
    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda k: seq)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "flow_user", "password": "x123456", "display_name": "U"})
        await c.post("/api/auth/register", json={"username": "flow_admin", "password": "x123456", "display_name": "A"})
        r = await c.post("/api/auth/login", json={"username": "flow_user", "password": "x123456"})
        h_user = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/auth/login", json={"username": "flow_admin", "password": "x123456"})
        h_admin = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 提权 admin
        await db_session.execute(update(User).where(User.username == "flow_admin").values(role_code="admin"))
        await db_session.commit()

        conv_id = (await c.post("/api/conversations", json={}, headers=h_user)).json()["id"]

        # 1. SSE 流：应收到 confirm_required（create，high）
        events = []
        async with c.stream("POST", "/api/chat/completions",
                            json={"conversation_id": conv_id, "message": "策划并发布国庆活动"},
                            headers=h_user) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        ev_names = [e["event"] for e in events]
        assert "confirm_required" in ev_names, ev_names
        assert "error" not in ev_names, events

        # 2. resume：high 确认后应继续走到 critical，返回 ok=False + approval_id
        r = await c.post("/api/chat/resume", json={"conversation_id": conv_id, "approved": True}, headers=h_user)
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is False, body
        approval_id = body["payload"]["approval_id"]
        assert approval_id

        # 3. 管理员审批 critical → decide 立即返回，图恢复在后台执行后落库
        r = await c.post(f"/api/approvals/{approval_id}/decide",
                         json={"approve": True, "comment": "ok"}, headers=h_admin)
        assert r.status_code == 200, r.text

        # 后台图恢复完成前 decide 已返回（前端即时反馈），轮询等待回复落库
        assistant = await _wait_assistant(c, conv_id, h_user)
        assert assistant, "后台恢复应落库 assistant"
        assert assistant[-1]["content"] == "最终方案已生成"

        # trace 终态同样由后台任务更新，轮询等待
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5.0:
            traces = (await c.get("/api/traces", headers=h_user)).json()
            trace = next(t for t in traces if t["conversation_id"] == conv_id)
            if trace["status"] == "completed":
                break
            await asyncio.sleep(0.1)
        assert trace["status"] == "completed", trace


@pytest.mark.asyncio
async def test_critical_rejection_still_replies(db_session, monkeypatch):
    """驳回 critical 审批：工具不执行，但图恢复完成并保存最终回复。"""
    await _stubs(monkeypatch)
    seq = SequencedLLM()
    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda k: seq)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "rej_user", "password": "x123456", "display_name": "U"})
        await c.post("/api/auth/register", json={"username": "rej_admin", "password": "x123456", "display_name": "A"})
        r = await c.post("/api/auth/login", json={"username": "rej_user", "password": "x123456"})
        h_user = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/auth/login", json={"username": "rej_admin", "password": "x123456"})
        h_admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
        await db_session.execute(update(User).where(User.username == "rej_admin").values(role_code="admin"))
        await db_session.commit()

        conv_id = (await c.post("/api/conversations", json={}, headers=h_user)).json()["id"]

        events = []
        async with c.stream("POST", "/api/chat/completions",
                            json={"conversation_id": conv_id, "message": "策划并发布国庆活动"},
                            headers=h_user) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        assert "confirm_required" in [e["event"] for e in events], events

        r = await c.post("/api/chat/resume", json={"conversation_id": conv_id, "approved": True}, headers=h_user)
        approval_id = r.json()["payload"]["approval_id"]

        # 驳回：decide 立即返回，图恢复在后台执行后落库，轮询等待
        r = await c.post(f"/api/approvals/{approval_id}/decide",
                         json={"approve": False, "comment": "暂不发布"}, headers=h_admin)
        assert r.status_code == 200, r.text

        assistant = await _wait_assistant(c, conv_id, h_user)
        assert assistant, "后台恢复应落库 assistant"
        assert assistant[-1]["content"] == "最终方案已生成"

        # 审批单状态应为 rejected
        r = await c.get("/api/approvals", params={"status": "rejected"}, headers=h_admin)
        assert any(a["id"] == approval_id for a in r.json()), r.text
