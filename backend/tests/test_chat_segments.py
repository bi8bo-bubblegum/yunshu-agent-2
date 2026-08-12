# backend/tests/test_chat_segments.py
"""回归：分段落库（优化项 2，方案 B）。

曾长期存在的问题：流式时前端拼所有 agent 的 token，DB 只落最后一段 agent_response。
中间 agent 产出（如营销方案）只存在于临时 SSE 流，refreshFromDb 后丢失，且用户看到的
与落库内容不一致（闪烁）。

修复：supervisor_node 把"上一轮 agent 输出"快照进 agent_outputs（图状态），
stream_chat / resume / 审批恢复按轮切分，各 agent 产出各落一条 assistant
（metadata 标记 agent + segment），最后一段为 final。单 agent 退化为 1 条，行为不变。

现在 agent→done 不回 supervisor，每轮只执行一个 agent（不再有多 agent 协作），
分段落库退化为单 agent final。多 agent 协作场景（marketing→sales）已被消灭。
"""
import json
from types import SimpleNamespace

import pytest
from httpx import AsyncClient, ASGITransport
from langchain_core.messages import AIMessage

from app.main import app
from app.models.chat import Conversation
from app.repositories.trace_repo import TraceRepository


async def _stubs(monkeypatch, spec):
    idx = [0]

    async def fake_route(message, agents):
        agent = spec[idx[0] % len(spec)]
        idx[0] += 1
        return {"agent": agent, "reason": "测试路由", "confidence": 0.9}

    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)

    async def _ctx(db, cid, **k):
        return ""

    async def _exp(db, uid, dept, q, **k):
        return ""

    async def _noop(*a, **k):
        return None

    async def _title(msg):
        return "测试标题"

    monkeypatch.setattr("app.memory.assembly.short_term.build_context", _ctx)
    monkeypatch.setattr("app.memory.assembly.pref_mem.build_context", _ctx)
    monkeypatch.setattr("app.memory.assembly.exp_mem.build_experience_context", _exp)
    # 知识库已改 search_knowledge 工具，不再自动装配，无需 mock
    monkeypatch.setattr("app.services.chat_service.maybe_extract_batch", _noop)
    monkeypatch.setattr("app.services.chat_service.distill_experience", _noop)
    monkeypatch.setattr("app.services.chat_service.save_personal_experience", _noop)
    monkeypatch.setattr("app.services.chat_service.maybe_roll_summary", _noop)
    monkeypatch.setattr("app.services.summary.generate_title", _title)

    class MktLLM:
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, messages):
            return AIMessage(content="营销方案已生成")

    class SalesLLM:
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, messages):
            return AIMessage(content="经营分析已完成")

    # ModelFactory.get_llm 是类方法：所有 agent 模块引用同一个类对象，
    # 必须按 model_key 返回不同 FakeLLM，不能逐个 agent patch（后者会覆盖前者）。
    from app.llm.factory import ModelFactory as LLMFactory

    def _fake_get_llm(model_key="default"):
        return SalesLLM() if model_key == "sales_analysis" else MktLLM()

    monkeypatch.setattr(LLMFactory, "get_llm",
                        classmethod(lambda cls, model_key="default": _fake_get_llm(model_key)))


@pytest.mark.asyncio
async def test_single_agent_no_step(monkeypatch):
    """单 agent 场景（marketing → done）：退化为 1 条 assistant（final），不产生 step 段落，
    与改造前行为一致。"""
    await _stubs(monkeypatch, ["marketing", "done"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "seg_user2", "password": "x123456", "display_name": "S2"})
        r = await c.post("/api/auth/login", json={"username": "seg_user2", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        conv_id = (await c.post("/api/conversations", json={}, headers=h)).json()["id"]

        async with c.stream("POST", "/api/chat/completions",
                            json={"conversation_id": conv_id, "message": "做一个营销方案"},
                            headers=h) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h)).json()
        assert [m["role"] for m in msgs] == ["user", "assistant"], msgs
        assert msgs[1]["content"] == "营销方案已生成"
        # 单 agent 只有一个 final 段落（无 step），metadata 标记 final
        assert msgs[1]["metadata"]["segment"] == "final"
        assert msgs[1]["metadata"]["agent"] == "marketing"


@pytest.mark.asyncio
async def test_no_new_output_no_duplicate_segments(monkeypatch):
    """多轮对话中某轮无新增产出（如 supervisor 直接 done）时，不得重复落库历史段落。

    曾真实事故：l0 == len(agent_outputs) 时 segments 走了 else 分支取全部历史，
    导致前面轮次的 step 段落被重复落库，前端刷新后中间消息重复/错乱。
    修复后 l0 >= len(outputs) 视为「本轮无新增」，segments 为空，只落最终答案一条。
    """
    await _stubs(monkeypatch, ["marketing", "done", "done"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "seg_user3", "password": "x123456", "display_name": "S3"})
        r = await c.post("/api/auth/login", json={"username": "seg_user3", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        conv_id = (await c.post("/api/conversations", json={}, headers=h)).json()["id"]

        # 第一轮：marketing 产出段落（step）→ done（final）
        async with c.stream("POST", "/api/chat/completions",
                            json={"conversation_id": conv_id, "message": "做一个营销方案"},
                            headers=h) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass
        # 第二轮：supervisor 直接 done（无 agent 执行，agent_outputs 无新增）
        async with c.stream("POST", "/api/chat/completions",
                            json={"conversation_id": conv_id, "message": "好的"},
                            headers=h) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h)).json()
        # 第一轮：user + marketing(final)（单 agent 无 step）；第二轮：user + 一条 final
        roles = [m["role"] for m in msgs]
        assert roles == ["user", "assistant", "user", "assistant"], roles
        # 关键：两轮各只有 1 条 assistant，第二轮没有重放第一轮的 agent_outputs。
        # 若 l0 == len(outputs) 仍走 else 取全部历史，第二轮会多出重复段落。
        # 第一轮带 agent 快照 metadata；第二轮无新增产出，落普通 assistant（metadata=None）。
        segments = [m["metadata"] for m in msgs if m["role"] == "assistant"]
        assert segments == [
            {"agent": "marketing", "segment": "final"},
            None,
        ], segments


class _CrashGraph:
    """模拟真实事故的假图：第一轮正常执行（产出段落 + 最终回复），第二轮图崩溃。

    崩溃后 aget_state 返回的仍是崩溃前 checkpoint（含第一轮 agent_response）——
    正是触发「回退上一轮消息」bug 的场景：segments 为空（agent_outputs 无本轮新增）
    + 图异常已捕获，旧逻辑 else 分支回退落上一轮 agent_response。"""

    def __init__(self):
        self.calls = 0
        self.snap = {"agent_outputs": [], "agent_response": "", "route_history": []}

    async def aget_state(self, config):
        return SimpleNamespace(values=self.snap)

    async def astream(self, inputs, config, **kwargs):
        self.calls += 1
        if self.calls == 1:
            # 第一轮正常执行：模拟 marketing 产出段落 + 最终回复写入 checkpoint
            self.snap = {
                "agent_outputs": [{"agent": "marketing", "content": "营销方案已生成"}],
                "agent_response": "营销方案已生成",
                "route_history": ["marketing"],
            }
            yield None  # 空 item 被 _run_graph 跳过，第一轮正常结束
            return
        # 第二轮：子图崩溃冒泡（真实事故：MCP 工具 up_occupancy 参数错误崩子图）
        raise RuntimeError("工具调用失败: MCP 传输错误")


@pytest.mark.asyncio
async def test_graph_error_no_fallback_to_old_message(monkeypatch, db_session):
    """图执行失败（工具失败崩子图）时不回退上一轮回复，落失败提示 + trace failed。

    真实事故链路：LLM 臆造 MCP 工具参数 → 服务器校验失败 → 工具异常崩子图 →
    父图 __error__ → stream_chat 的 _run_graph 捕获异常 → aget_state 返回崩溃前
    checkpoint（agent_outputs 无本轮新增）→ segments 为空。旧逻辑 else 分支回退落
    上一轮 agent_response（前端重复显示上一次的回复）；修复后落明确失败提示 +
    trace failed + SSE error 事件。注入假图（第二轮 astream 抛异常），不污染真实
    缓存主图。"""
    await _stubs(monkeypatch, ["marketing", "done"])
    fake = _CrashGraph()

    async def _get_graph():
        return fake

    monkeypatch.setattr("app.services.chat_service.get_graph", _get_graph)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "seg_fail", "password": "x123456", "display_name": "S"})
        r = await c.post("/api/auth/login", json={"username": "seg_fail", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        conv_id = (await c.post("/api/conversations", json={}, headers=h)).json()["id"]

        def _sse(body: str) -> list[dict]:
            return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]

        # 第一轮：图正常执行，落「营销方案已生成」（即上一轮回复，作为对照基线）
        body1 = ""
        async with c.stream("POST", "/api/chat/completions",
                            json={"conversation_id": conv_id, "message": "做一个营销方案"},
                            headers=h) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                body1 += line + "\n"
        assert any(e["event"] == "answer" for e in _sse(body1)), _sse(body1)

        # 第二轮：图崩溃 → SSE 必须含 error 事件，而不是静默回退上一轮回复
        body2 = ""
        async with c.stream("POST", "/api/chat/completions",
                            json={"conversation_id": conv_id, "message": "再查一下"},
                            headers=h) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                body2 += line + "\n"
        assert any(e["event"] == "error" for e in _sse(body2)), _sse(body2)

        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h)).json()
        assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"], [m["role"] for m in msgs]
        # 关键断言：本轮 assistant 是失败提示，绝不是上一轮回复
        assert msgs[-1]["content"] != "营销方案已生成", msgs[-1]["content"]
        assert "失败" in msgs[-1]["content"], msgs[-1]["content"]
        assert msgs[-1]["metadata"]["failed"] is True
        # trace 终态 failed（区别于 interrupted/completed，供 Traces.vue 红标展示）
        conv = await db_session.get(Conversation, conv_id)
        assert conv.current_trace_id, "失败后 current_trace_id 应指向本轮 trace"
        trace = await TraceRepository(db_session).get(conv.current_trace_id)
        assert trace.status == "failed", trace.status
