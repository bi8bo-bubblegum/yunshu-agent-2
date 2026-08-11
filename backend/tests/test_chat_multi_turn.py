"""回归：多轮对话历史不得重复注入 / 累积。

曾出现严重 bug：stream_chat 每轮把 DB 里的历史消息回灌进图输入（messages channel），
而 LangGraph checkpointer（thread_id=conversation_id）已经保存了历史，messages 又带 add
追加语义，导致同一份历史每轮被合并两次、逐轮翻倍膨胀。agent 上下文错乱后出现两类现象：
- 复读用户消息（assistant 把 user 的话原样输出）；
- 重复上一轮的完整回复，不回答本轮问题。

另有根因：子图（compile(checkpointer=True)）在固定 checkpoint_ns 下累积历史，
与父图每次传入的完整 messages 用 add 合并重复。修复：wrap_subgraph 让子图每次在
「父图当前 checkpoint id 派生的独立 sub-thread」上从空 checkpoint 全新开始。

本文件两个测试：
- 多轮场景（每轮 marketing×1）：第二轮必须正常回复，不复读用户消息、不重复第一轮回复；
- 同轮多次路由场景（marketing×2 → done）：同一轮内重复路由到同一 agent 时子图不膨胀。
"""
import pytest
from httpx import AsyncClient, ASGITransport
from langchain_core.messages import AIMessage, HumanMessage

from app.main import app


class FakeLLM:
    """marketing agent 主 LLM：按「最后一条用户消息」返回确定性回复。

    这样每轮输入不同 → 输出不同，可精确验证：第二轮回复不复读第一轮内容、
    第一轮已落库的 assistant 消息不被后续轮次改写。"""

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        for m in reversed(messages):
            if isinstance(m, HumanMessage):
                return AIMessage(content=f"回复:{m.content}")
        return AIMessage(content="回复:（无用户消息）")


async def _stubs(monkeypatch, spec):
    # 闭包持有路由状态，避免跨测试共享
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
    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda k: FakeLLM())


async def _stream(client, headers, conv_id, message):
    async with client.stream("POST", "/api/chat/completions",
                             json={"conversation_id": conv_id, "message": message},
                             headers=headers) as resp:
        assert resp.status_code == 200
        async for _ in resp.aiter_lines():
            pass


async def _final_messages(conv_id):
    """读图最终状态的 messages（checkpoint 合并后的完整消息序列）。"""
    from app.agents.graph import get_graph
    graph = await get_graph()
    snap = await graph.aget_state({"configurable": {"thread_id": conv_id}})
    return (snap.values or {}).get("messages", []), snap.values


@pytest.mark.asyncio
async def test_multi_turn_no_history_duplication(monkeypatch):
    """两轮对话（每轮 marketing×1 → done）：第二轮必须正常回复，不复读用户消息。"""
    # agent→done 不回 supervisor，每轮只调一次 route_decision（路由 agent）
    await _stubs(monkeypatch, ["marketing", "marketing"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "mt_user", "password": "x123456", "display_name": "M"})
        r = await c.post("/api/auth/login", json={"username": "mt_user", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        conv_id = (await c.post("/api/conversations", json={}, headers=h)).json()["id"]

        await _stream(c, h, conv_id, "你好")
        await _stream(c, h, conv_id, "预算太高了")

        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h)).json()
        # 序列必须干净：user → assistant → user → assistant，无多余重复
        assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"], msgs
        # 用户流程复现：提问「你好」→ 回复「回复:你好」；再提问「预算太高了」
        # → 上一条回复必须保持不变（仍是「回复:你好」），本轮回复新内容「回复:预算太高了」
        assert msgs[0]["content"] == "你好"
        assert msgs[1]["content"] == "回复:你好"   # 上一条回复：未因第二轮被改写
        assert msgs[2]["content"] == "预算太高了"
        # bug 现象：assistant 复读用户消息 / 重复第一轮回复 / 本轮回复与上轮相同
        assert msgs[3]["content"] == "回复:预算太高了"
        assert msgs[3]["content"] != msgs[1]["content"]  # 本轮不复读上一轮内容

        # 图最终状态：期望 [H1, A1, H2, A2]，无重复块（旧 bug 下 "你好" 会重复、超 4 条）
        cp_msgs, values = await _final_messages(conv_id)
        roles = [m.type for m in cp_msgs]
        contents = [str(getattr(m, "content", m))[:12] for m in cp_msgs]
        assert roles == ["human", "ai", "human", "ai"], (roles, contents)
        assert contents.count("你好") == 1, contents
        assert values.get("agent_response") == "回复:预算太高了", values.get("agent_response")


@pytest.mark.asyncio
async def test_agent_direct_to_done(monkeypatch):
    """agent 执行完直接进 done，不回 supervisor 做二次路由。

    原设计 agent→supervisor→done，二次路由只多花一次 LLM 调用且偶发
    自相矛盾导致空转（trace 实证 marketing×4）。改为 agent→done，
    route_history 只含 agent（不含 done），单次路由即结束。
    """
    await _stubs(monkeypatch, ["marketing"])

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        await c.post("/api/auth/register", json={"username": "mt_user2", "password": "x123456", "display_name": "M2"})
        r = await c.post("/api/auth/login", json={"username": "mt_user2", "password": "x123456"})
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        conv_id = (await c.post("/api/conversations", json={}, headers=h)).json()["id"]

        await _stream(c, h, conv_id, "你好")

        msgs = (await c.get(f"/api/conversations/{conv_id}/messages", headers=h)).json()
        # agent→done：只落 1 条 assistant，不回 supervisor 二次路由
        assert [m["role"] for m in msgs] == ["user", "assistant"], msgs
        assert msgs[1]["content"] == "回复:你好"

        # 图最终状态：route_history = [marketing]（不含 done，agent 直接到 done）
        cp_msgs, values = await _final_messages(conv_id)
        assert values.get("route_history") == ["marketing"], values.get("route_history")
        assert values.get("agent_response") == "回复:你好", values.get("agent_response")
