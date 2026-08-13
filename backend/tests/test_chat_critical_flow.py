"""回归：流式聊天 + critical 双审批链全链路。

create_marketing_campaign 已从 high（即时确认）改为 critical（创建活动 = 提交 OA 审批表单），
publish_campaign 保持 critical。用 FakeLLM 强制触发 create(critical) → publish(critical)
工具链，验证：SSE confirm_required → 逐个钉钉审批事件回写（本地 decide 已下线）→
后台图恢复 → 两个工具卡片 + 最终回复落库。
"""
import asyncio
import json
import time

import pytest
from httpx import AsyncClient, ASGITransport
from langchain_core.messages import AIMessage
from sqlalchemy import select, update

from app.main import app
from app.models.dingtalk import ApprovalBinding
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
    """按调用顺序返回：create 工具调用 → publish 工具调用 → 最终方案（双 critical 审批链）。"""

    def __init__(self, reject_after_create: bool = False):
        self.calls = 0
        # 驳回场景：create 被拒后第二次直接输出最终方案，不再调 publish
        self.reject_after_create = reject_after_create

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
        if self.reject_after_create:
            return AIMessage(content="最终方案已生成")
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
async def _submit_and_approve(db_session, approval_id, staff="flow_admin_ding"):
    """手动提交审批单到钉钉并模拟审批通过事件回写（复用 mock_dingtalk_push 的 fake push）。"""
    from app.services.approval_service import ApprovalService
    svc = ApprovalService(db_session)
    binding = await svc.submit_to_dingtalk(approval_id=approval_id)
    from app.services.dingtalk.approval_gateway import handle_approval_instance_change
    await handle_approval_instance_change({"processInstanceId": binding.process_instance_id,
                                           "type": "finish", "result": "agree", "staffId": staff})


async def _wait_next_approval(c, h, exclude_id, timeout=10.0):
    """轮询等待除 exclude_id 外出现新的 pending 审批单（后台恢复图新建的后续审批单）。"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        rows = (await c.get("/api/approvals", params={"status": "pending"}, headers=h)).json()
        others = [r for r in rows if r["id"] != exclude_id]
        if others:
            return others[0]
        await asyncio.sleep(0.2)
    raise AssertionError(f"等待新审批单超时: {rows}")


@pytest.mark.asyncio
async def test_critical_approval_flow(db_session, monkeypatch, mock_dingtalk_push):
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

        # 1. SSE 流：create(critical) 创建审批单并 interrupt，应收到 confirm_required
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
        create_approval_id = next(
            e["payload"]["approval_id"] for e in events if e["event"] == "confirm_required")
        # 审批单标题含活动名（友好化）
        rows = (await c.get("/api/approvals", params={"status": "pending"}, headers=h_user)).json()
        assert rows and "创建营销活动：国庆大促" in rows[0]["title"], rows

        # 2. 创建活动审批通过 → 后台恢复图 → create 执行 → publish(critical) 建第二个审批单
        await _submit_and_approve(db_session, create_approval_id)
        publish_approval = await _wait_next_approval(c, h_user, create_approval_id)
        publish_approval_id = publish_approval["id"]

        # 3. 发布审批通过 → 后台恢复图 → publish 执行 → 最终方案落库
        await _submit_and_approve(db_session, publish_approval_id)
        assistant = await _wait_assistant(c, conv_id, h_user)
        assert assistant, "后台恢复应落库 assistant"
        assert assistant[-1]["content"] == "最终方案已生成"
        # 两个工具卡片：create + publish 均 success
        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h_user)).json()
        tools = [m for m in msgs if m["role"] == "tool"]
        assert [t["metadata"]["tool"] for t in tools] == [
            "create_marketing_campaign", "publish_campaign"], tools
        assert all(t["metadata"]["status"] == "success" for t in tools)

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
async def test_critical_rejection_still_replies(db_session, monkeypatch, mock_dingtalk_push):
    """驳回创建活动审批：create 不执行，图恢复后 agent 继续生成最终回复并落库。"""
    await _stubs(monkeypatch)
    seq = SequencedLLM(reject_after_create=True)
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
        create_approval_id = next(
            e["payload"]["approval_id"] for e in events if e["event"] == "confirm_required")

        # 驳回创建活动审批：create 不执行，图恢复后 agent 直接给最终方案
        from app.services.approval_service import ApprovalService
        svc = ApprovalService(db_session)
        binding = await svc.submit_to_dingtalk(approval_id=create_approval_id)
        from app.services.dingtalk.approval_gateway import handle_approval_instance_change
        await handle_approval_instance_change({"processInstanceId": binding.process_instance_id,
                                               "type": "finish", "result": "refuse",
                                               "staffId": "flow_admin_ding"})

        assistant = await _wait_assistant(c, conv_id, h_user)
        assert assistant, "后台恢复应落库 assistant"
        assert assistant[-1]["content"] == "最终方案已生成"

        # 审批单状态应为 rejected
        r = await c.get("/api/approvals", params={"status": "rejected"}, headers=h_admin)
        assert any(a["id"] == create_approval_id for a in r.json()), r.text
