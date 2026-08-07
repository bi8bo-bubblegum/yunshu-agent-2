"""回归：多轮对话历史不得重复注入 / 累积。

曾出现严重 bug：stream_chat 每轮把 DB 里的历史消息回灌进图输入（messages channel），
而 LangGraph checkpointer（thread_id=conversation_id）已经保存了历史，messages 又带 add
追加语义，导致同一份历史每轮被合并两次、逐轮翻倍膨胀。agent 上下文错乱后出现两类现象：
- 复读用户消息（assistant 把 user 的话原样输出）；
- 重复上一轮的完整回复，不回答本轮问题。

本测试跑两轮真实对话，断言 DB 消息序列干净、第二轮 assistant 正常回复，
不复读用户消息、不重复第一轮回复。
"""
import pytest
from httpx import AsyncClient, ASGITransport
from langchain_core.messages import AIMessage

from app.main import app


class FakeLLM:
    """marketing agent 主 LLM：始终直接给出文本回复，不触发工具调用。"""

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return AIMessage(content="营销方案已生成")


async def _stubs(monkeypatch):
    # 每轮 supervisor 两次路由（入口 + 出口判断），两轮共 4 次
    routes = iter([
        {"agent": "marketing", "reason": "营销策划", "confidence": 0.9},
        {"agent": "done", "reason": "任务完成", "confidence": 0.95},
        {"agent": "marketing", "reason": "营销策划", "confidence": 0.9},
        {"agent": "done", "reason": "任务完成", "confidence": 0.95},
    ])

    async def fake_route(message, agents):
        return next(routes)

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
    monkeypatch.setattr("app.memory.assembly.knowledge.retrieve_knowledge", _ctx)
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


@pytest.mark.asyncio
async def test_multi_turn_no_history_duplication(monkeypatch):
    """两轮对话：第二轮必须正常回复，不复读用户消息、不重复第一轮回复。"""
    await _stubs(monkeypatch)

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
        assert msgs[0]["content"] == "你好"
        assert msgs[1]["content"] == "营销方案已生成"
        assert msgs[2]["content"] == "预算太高了"
        # bug 现象：assistant 复读用户消息 / 重复第一轮回复
        assert msgs[3]["content"] == "营销方案已生成"
