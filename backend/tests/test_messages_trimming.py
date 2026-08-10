# backend/tests/test_messages_trimming.py
"""回归：图内消息超长裁剪（messages 通道 add_messages + RemoveMessage）。

曾长期存在的问题：messages 通道用 operator.add（纯追加），只增不减。长对话时
图内消息无限累积，传给 LLM 的 token 线性膨胀，迟早爆上下文；滚动摘要
（conv.summary）生成后旧消息仍留在 messages 里，与摘要内容重叠喂两遍。

修复：messages 通道改为 add_messages（LangGraph 语义，自动为无 id 消息分配 id、
RemoveMessage 按 id 删除），done_node 用 RemoveMessage 裁剪窗口外消息
（MAX_MESSAGES=100 → 保留 RETAIN_MESSAGES=60），checkpointer 持久化裁剪后状态，
下一轮只带窗口内消息；窗口外由滚动摘要（memory 装配注入）兜底。
"""
import pytest
from langchain_core.messages import HumanMessage

from app.agents.graph import _trim_messages, MAX_MESSAGES, RETAIN_MESSAGES


def test_trim_messages_short_noop():
    """未超长：不生成任何 RemoveMessage，不裁剪。"""
    msgs = [HumanMessage(id=f"m{i}", content=f"msg{i}") for i in range(5)]
    assert _trim_messages(msgs) == []


def test_trim_messages_oversize_generates_removals():
    """超长：只对窗口外消息生成 RemoveMessage，保留最近 retain 条。"""
    msgs = [HumanMessage(id=f"m{i}", content=f"msg{i}") for i in range(MAX_MESSAGES + 10)]
    removals = _trim_messages(msgs)
    assert len(removals) == len(msgs) - RETAIN_MESSAGES
    # 删除的是最旧的窗口外消息；窗口内（最近 retain 条）不得被删除
    removed_ids = {r.id for r in removals}
    keep_ids = {m.id for m in msgs[-RETAIN_MESSAGES:]}
    assert not (removed_ids & keep_ids)


@pytest.mark.asyncio
async def test_graph_trims_oversized_messages(monkeypatch):
    """图执行后：超长 messages 被裁剪到保留窗口，checkpointer 持久化裁剪后状态。

    验证 add_messages 语义在真实图里生效：注入远超阈值的历史消息 → done_node
    裁剪 → 下一状态只剩窗口内消息（旧消息被 RemoveMessage 按 id 删除）。"""
    from app.agents.graph import get_graph

    async def fake_route(message, agents):
        return {"agent": "done", "reason": "测试", "confidence": 0.9}

    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)

    graph = await get_graph()
    thread = {"configurable": {"thread_id": "trim-test-conv"}}
    n = MAX_MESSAGES + 30
    await graph.ainvoke(
        {"messages": [HumanMessage(content=f"历史消息{i}") for i in range(n)]},
        config=thread,
    )
    snap = await graph.aget_state(thread)
    msgs = (snap.values or {}).get("messages", [])
    assert len(msgs) == RETAIN_MESSAGES, len(msgs)
    # 保留的是最近的消息，裁剪掉的是最旧的；所有消息都有 id（add_messages 保证）
    contents = [str(getattr(m, "content", m)) for m in msgs]
    assert contents[0].startswith("历史消息")
    assert all(m.id for m in msgs)
    assert snap.values.get("agent_response") == "已完成"
