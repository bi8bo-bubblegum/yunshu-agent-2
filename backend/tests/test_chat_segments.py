# backend/tests/test_chat_segments.py
"""回归：多 agent 分段落库（优化项 2，方案 B）。

曾长期存在的问题：流式时前端拼所有 agent 的 token，DB 只落最后一段 agent_response。
中间 agent 产出（如营销方案）只存在于临时 SSE 流，refreshFromDb 后丢失，且用户看到的
与落库内容不一致（闪烁）。

修复：supervisor_node 把"上一轮 agent 输出"快照进 agent_outputs（图状态），
stream_chat / resume / 审批恢复按轮切分，各 agent 产出各落一条 assistant
（metadata 标记 agent + segment），最后一段为 final。单 agent 退化为 1 条，行为不变。
"""
import pytest
from httpx import AsyncClient, ASGITransport
from langchain_core.messages import AIMessage

from app.main import app


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
async def test_multi_agent_segments_persisted(monkeypatch):
    """多 agent 协作（marketing → sales → done）：各 agent 产出各落一条 assistant，
    中间产出不丢失，metadata 标记 agent/segment，最后一段为 final。"""
    await _stubs(monkeypatch, ["marketing", "sales_analysis", "done"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "seg_user", "password": "x123456", "display_name": "S"})
        r = await c.post("/api/auth/login", json={"username": "seg_user", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        conv_id = (await c.post("/api/conversations", json={}, headers=h)).json()["id"]

        async with c.stream("POST", "/api/chat/completions",
                            json={"conversation_id": conv_id, "message": "先策划再分析"},
                            headers=h) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h)).json()
        # 序列：user → 营销(step) → 经营(final)，中间产出不再丢失
        assert [m["role"] for m in msgs] == ["user", "assistant", "assistant"], msgs
        assert msgs[0]["content"] == "先策划再分析"
        # 营销产出：step 段落，agent=marketing
        assert msgs[1]["content"] == "营销方案已生成"
        assert msgs[1]["metadata"] == {"agent": "marketing", "segment": "step"}
        # 经营产出：final 段落（最终答案），agent=sales_analysis
        assert msgs[2]["content"] == "经营分析已完成"
        assert msgs[2]["metadata"] == {"agent": "sales_analysis", "segment": "final"}


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
