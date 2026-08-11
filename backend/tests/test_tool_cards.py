"""结构化工具卡片：tool 消息落库（role="tool"）+ 终态才落库 + 错误状态。

工具调用从「流式期间一行文本日志」升级为结构化卡片，持久化到 Message：
role="tool" + metadata.kind="tool"（含 tool/args/result/status）。验证：
1. low 风险工具：落库 tool 消息（success），SSE tool_start 带结构化 args + run_id。
2. 多级 interrupt（high→critical）：中间状态不落库，审批通过后终态一次性落全部工具卡片。
3. 工具返回 error：tool 消息 status=="error"。
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
from app.tools.facade import facade


async def _wait_msgs(c, conv_id, h, want_tools, timeout=5.0):
    """轮询等待会话出现 want_tools 条 tool 消息（审批后台恢复后落库，不阻塞响应）。"""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h)).json()
        if sum(1 for m in msgs if m["role"] == "tool") >= want_tools:
            return msgs
        await asyncio.sleep(0.1)
    return []


class QueryLLM:
    """先返回 query_marketing_campaigns 工具调用，再返回最终文本。"""

    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[{
                "name": "query_marketing_campaigns",
                "args": {"status": "active"},
                "id": "q1", "type": "tool_call",
            }])
        return AIMessage(content="进行中的营销活动查询完成")


class SequencedLLM:
    """按调用顺序返回：create 工具调用 → publish 工具调用 → 最终方案（多级 interrupt）。"""

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


async def _stubs(monkeypatch, llm):
    """单轮流式路径：路由序列 marketing→done + 记忆/沉淀 noop + ModelFactory 统一返回 llm。"""
    _route_idx = [0]

    async def fake_route(message, agents):
        # 序列化路由：第一次进 marketing，第二次 done（supervisor 不重复路由同 agent，
        # 避免 agent 反复执行产生多条段落）
        spec = ["marketing", "done"]
        agent = spec[_route_idx[0] % len(spec)]
        _route_idx[0] += 1
        return {"agent": agent, "reason": "测试路由", "confidence": 0.9}

    async def _ctx(db, cid, **k):
        return ""

    async def _exp(db, uid, dept, q, **k):
        return ""

    async def _noop(*a, **k):
        return None

    async def _title(msg):
        return "测试标题"

    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)
    monkeypatch.setattr("app.memory.assembly.short_term.build_context", _ctx)
    monkeypatch.setattr("app.memory.assembly.pref_mem.build_context", _ctx)
    monkeypatch.setattr("app.memory.assembly.exp_mem.build_experience_context", _exp)
    monkeypatch.setattr("app.services.chat_service.maybe_extract_batch", _noop)
    monkeypatch.setattr("app.services.chat_service.distill_experience", _noop)
    monkeypatch.setattr("app.services.chat_service.save_personal_experience", _noop)
    monkeypatch.setattr("app.services.chat_service.maybe_roll_summary", _noop)
    monkeypatch.setattr("app.services.summary.generate_title", _title)
    # ModelFactory.get_llm 是类方法：所有 agent 引用同一类对象，统一返回 llm
    from app.llm.factory import ModelFactory as LLMFactory
    monkeypatch.setattr(LLMFactory, "get_llm",
                        classmethod(lambda cls, model_key="default": llm))


async def _stubs_critical(monkeypatch):
    """多级 interrupt 全链路：与 test_chat_critical_flow._stubs 对齐（resume/审批路径按源模块 stub）。"""
    _route_idx = [0]

    async def fake_route(message, agents):
        # 序列化路由：第一次进 marketing，第二次 done（interrupt 后 resume 到终态时结束）
        spec = ["marketing", "done"]
        agent = spec[_route_idx[0] % len(spec)]
        _route_idx[0] += 1
        return {"agent": agent, "reason": "r", "confidence": 0.9}

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
async def test_tool_card_persisted(monkeypatch):
    """low 风险工具：落库 tool 消息（kind/tool/args/result/status=success），
    SSE tool_start 带结构化 args + run_id（前端实时渲染卡片用）。"""
    await _stubs(monkeypatch, QueryLLM())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "card_user", "password": "x123456", "display_name": "U"})
        r = await c.post("/api/auth/login", json={"username": "card_user", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        conv_id = (await c.post("/api/conversations", json={}, headers=h)).json()["id"]

        events = []
        async with c.stream("POST", "/api/chat/completions",
                            json={"conversation_id": conv_id, "message": "查一下进行中的营销活动"},
                            headers=h) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        # SSE：tool_start 带结构化 args + run_id（前端按 run_id 配对 start/end）
        starts = [e for e in events if e.get("event") == "tool_start"]
        assert starts, [e.get("event") for e in events]
        assert starts[0]["tool"] == "query_marketing_campaigns"
        assert starts[0]["args"] == {"status": "active"}, starts[0]["args"]
        assert starts[0].get("run_id"), starts[0]

        # 落库：user → tool → assistant
        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h)).json()
        assert [m["role"] for m in msgs] == ["user", "tool", "assistant"], msgs
        tool = msgs[1]
        assert tool["content"] == "🔧 query_marketing_campaigns"
        md = tool["metadata"]
        assert md["kind"] == "tool"
        assert md["tool"] == "query_marketing_campaigns"
        assert md["args"] == {"status": "active"}
        assert md["status"] == "success"
        # result 是 active 活动列表（纯函数查询，非空）
        assert isinstance(md["result"], list) and md["result"], md["result"]


@pytest.mark.asyncio
async def test_interrupt_no_tool_rows_until_terminal(db_session, monkeypatch):
    """多级 interrupt：初始 stream 与 resume（二次 interrupt）都不落库（避免 resume 重放重复卡片），
    审批通过后终态一次性落 2 条工具卡片（create + publish，均 success）。"""
    await _stubs_critical(monkeypatch)
    seq = SequencedLLM()
    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda k: seq)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "ic_user", "password": "x123456", "display_name": "U"})
        await c.post("/api/auth/register", json={"username": "ic_admin", "password": "x123456", "display_name": "A"})
        r = await c.post("/api/auth/login", json={"username": "ic_user", "password": "x123456"})
        h_user = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = await c.post("/api/auth/login", json={"username": "ic_admin", "password": "x123456"})
        h_admin = {"Authorization": f"Bearer {r.json()['access_token']}"}
        await db_session.execute(update(User).where(User.username == "ic_admin").values(role_code="admin"))
        await db_session.commit()

        conv_id = (await c.post("/api/conversations", json={}, headers=h_user)).json()["id"]

        # 1. 初始 stream：create(high) interrupt，仅 user 消息（工具卡片终态才落库）
        events = []
        async with c.stream("POST", "/api/chat/completions",
                            json={"conversation_id": conv_id, "message": "策划并发布国庆活动"},
                            headers=h_user) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        assert "confirm_required" in [e["event"] for e in events], events
        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h_user)).json()
        assert [m["role"] for m in msgs] == ["user"], msgs

        # 2. resume：create 确认执行成功，但 publish(critical) 二次 interrupt，仍不落库
        r = await c.post("/api/chat/resume", json={"conversation_id": conv_id, "approved": True}, headers=h_user)
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is False, body
        approval_id = body["payload"]["approval_id"]
        assert approval_id
        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h_user)).json()
        assert [m["role"] for m in msgs] == ["user"], msgs

        # 3. 审批通过 → 后台恢复 → 终态一次性落库：create + publish 2 条工具卡片，均 success
        r = await c.post(f"/api/approvals/{approval_id}/decide",
                         json={"approve": True, "comment": "ok"}, headers=h_admin)
        assert r.status_code == 200, r.text
        msgs = await _wait_msgs(c, conv_id, h_user, want_tools=2)
        tools = [m for m in msgs if m["role"] == "tool"]
        assert len(tools) == 2, [m["role"] for m in msgs]
        assert [t["metadata"]["tool"] for t in tools] == [
            "create_marketing_campaign", "publish_campaign"], tools
        assert all(t["metadata"]["status"] == "success" for t in tools)
        # 最终回复已落库（assistant 在工具卡片之后）
        assert [m["role"] for m in msgs] == ["user", "tool", "tool", "assistant"], msgs
        assert msgs[-1]["content"] == "最终方案已生成"


@pytest.mark.asyncio
async def test_tool_error_status(monkeypatch):
    """工具返回 error dict：tool 消息 status=="error"（_looks_like_error 识别）。"""
    async def _err(**kwargs):
        return {"error": "模拟工具执行失败"}

    # facade 是全局单例：替换查询工具实现，monkeypatch 自动恢复。
    # get_graph() 缓存主图（工具 fn 在构建时绑定），须失效重建让 _err 生效
    monkeypatch.setattr(facade._tools["query_marketing_campaigns"], "fn", _err)
    from app.agents.graph import invalidate_graph
    invalidate_graph()
    await _stubs(monkeypatch, QueryLLM())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "err_user", "password": "x123456", "display_name": "U"})
        r = await c.post("/api/auth/login", json={"username": "err_user", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        conv_id = (await c.post("/api/conversations", json={}, headers=h)).json()["id"]

        async with c.stream("POST", "/api/chat/completions",
                            json={"conversation_id": conv_id, "message": "查一下进行中的营销活动"},
                            headers=h) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h)).json()
        assert [m["role"] for m in msgs] == ["user", "tool", "assistant"], msgs
        md = msgs[1]["metadata"]
        assert md["status"] == "error"
        assert md["result"] == {"error": "模拟工具执行失败"}
        # 工具出错不影响最终回复落库
        assert msgs[2]["content"] == "进行中的营销活动查询完成"
