# backend/tests/test_chat_abort.py
"""用户手动终止对话：stream_chat 取消处理单元测试。

前端点击「终止」→ abort 流式请求 → 客户端断开时 Starlette 对 SSE async generator
调 aclose()，在挂起点抛 GeneratorExit（继承 BaseException，_run_graph 的 except
Exception 捕获不到，graph_task 会成孤儿继续跑完图）。stream_chat 主循环用
except BaseException 兜底：取消后台图执行 + 把已生成内容（半截回答 + 已完成工具
卡片）落库 + 标记 trace 终态 aborted（区别于 interrupted，防 resume/审批误恢复）。
直接对 service.stream_chat 生成器消费 start/token 后 aclose() 模拟终止。"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.models.chat import Conversation
from app.models.org import User
from app.repositories.conversation_repo import MessageRepository
from app.repositories.trace_repo import TraceRepository
from app.services.chat_service import ChatService, _bg_abort_tasks


async def _wait_abort_settle(timeout=3.0):
    """等独立收尾 task 完成：终止后落库在独立 task + 独立 session 中执行，
    aclose() 返回时收尾可能尚未完成，需等待 _bg_abort_tasks 清空。"""
    t0 = asyncio.get_event_loop().time()
    while _bg_abort_tasks and asyncio.get_event_loop().time() - t0 < timeout:
        await asyncio.sleep(0.05)


class _State:
    """FakeGraph.aget_state 返回的 snapshot 壳。"""

    def __init__(self, values: dict):
        self.values = values


class SlowGraph:
    """模拟「图执行中」：推送一个 token 后挂起，直到被取消。"""

    def __init__(self):
        self.cancelled = False

    async def aget_state(self, config):
        return _State({"agent_outputs": []})

    async def astream(self, inputs, config, **kwargs):
        queue = config["configurable"]["sse_queue"]
        queue.put_nowait({"event": "token", "content": "半截回答"})
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield  # 永不到达（保持 async generator）


class NoTokenGraph(SlowGraph):
    """终止发生在首个 token 之前：astream 直接挂起，不推送任何 token。"""

    def __init__(self):
        super().__init__()
        self.started = False  # astream 是否被调用（图是否已启动）

    async def astream(self, inputs, config, **kwargs):
        self.started = True
        try:
            await asyncio.sleep(999)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield


class QuickGraph:
    """正常完成的图：推送 token 后立即结束，走正常落库路径（回归保护）。"""

    def __init__(self):
        self.snap_calls = 0

    async def aget_state(self, config):
        self.snap_calls += 1
        if self.snap_calls == 1:
            return _State({"agent_outputs": []})  # pre_snap
        return _State({"agent_response": "完整回答", "agent_outputs": [], "route_history": []})

    async def astream(self, inputs, config, **kwargs):
        queue = config["configurable"]["sse_queue"]
        queue.put_nowait({"event": "token", "content": "完整回答"})
        yield None  # 空 item 被 _run_graph 跳过，随后 astream 正常结束


async def _stubs(monkeypatch):
    """取消处理测试的公共 stub：记忆装配为空 + 记忆沉淀/标题后台任务 noop。"""
    async def _mem(db, uid, cid, dep, msg):
        return ""

    async def _noop(*a, **k):
        return None

    async def _title(msg):
        return "测试标题"

    monkeypatch.setattr("app.services.chat_service.assemble_memory", _mem)
    monkeypatch.setattr("app.services.chat_service.maybe_extract_batch", _noop)
    monkeypatch.setattr("app.services.chat_service.distill_experience", _noop)
    monkeypatch.setattr("app.services.chat_service.save_personal_experience", _noop)
    monkeypatch.setattr("app.services.chat_service.maybe_roll_summary", _noop)
    monkeypatch.setattr("app.services.summary.generate_title", _title)


async def _seed_user_conv(db_session):
    """建一个用户 + 会话，返回 (user_id, conv_id)。"""
    user = User(username="abort_user", password_hash="x", display_name="U")
    db_session.add(user)
    await db_session.flush()
    conv = Conversation(user_id=user.id)
    db_session.add(conv)
    await db_session.commit()
    return user.id, conv.id


@pytest.mark.asyncio
async def test_abort_midstream_persists_partial(db_session, monkeypatch):
    """终止在 token 已推送后：半截回答落库 + trace aborted + 图已取消 + current_trace_id 清空。"""
    await _stubs(monkeypatch)
    fake = SlowGraph()

    async def _get_graph():
        return fake

    monkeypatch.setattr("app.services.chat_service.get_graph", _get_graph)
    user_id, conv_id = await _seed_user_conv(db_session)

    gen = ChatService(db_session).stream_chat(user_id, conv_id, "测试消息")
    evt = json.loads(await gen.__anext__())
    assert evt["event"] == "start"
    trace_id = evt["trace_id"]
    evt = json.loads(await gen.__anext__())
    assert evt["event"] == "token"
    await gen.aclose()  # 模拟客户端断开 → 主循环抛 GeneratorExit → 取消处理
    await _wait_abort_settle()  # 等独立收尾 task 完成落库

    # 半截回答已落库（刷新后聊天记录不丢）
    msgs = await MessageRepository(db_session).list_by_conversation(conv_id)
    assert [m.role for m in msgs] == ["user", "assistant"], [m.role for m in msgs]
    assert msgs[-1].content == "半截回答", msgs[-1].content
    # trace 终态 aborted（区别于 interrupted，防 resume 误恢复）
    trace = await TraceRepository(db_session).get(trace_id)
    assert trace.status == "aborted", trace.status
    # 后台图任务已被取消（无孤儿任务继续跑）
    assert fake.cancelled is True
    # current_trace_id 已清空
    conv = await db_session.get(Conversation, conv_id)
    assert conv.current_trace_id is None


@pytest.mark.asyncio
async def test_abort_before_first_token_no_empty_row(db_session, monkeypatch):
    """终止在首个 token 之前：无任何产出则不落库空白 assistant（无空白气泡），trace 仍 aborted。"""
    await _stubs(monkeypatch)
    fake = NoTokenGraph()

    async def _get_graph():
        return fake

    monkeypatch.setattr("app.services.chat_service.get_graph", _get_graph)
    user_id, conv_id = await _seed_user_conv(db_session)

    gen = ChatService(db_session).stream_chat(user_id, conv_id, "测试消息")
    evt = json.loads(await gen.__anext__())
    assert evt["event"] == "start"
    trace_id = evt["trace_id"]
    await gen.aclose()
    await _wait_abort_settle()  # 等独立收尾 task 完成落库

    msgs = await MessageRepository(db_session).list_by_conversation(conv_id)
    assert [m.role for m in msgs] == ["user"], [m.role for m in msgs]
    trace = await TraceRepository(db_session).get(trace_id)
    assert trace.status == "aborted"
    # 图尚未启动（graph_task 未创建）：无孤儿任务，无需取消
    assert fake.started is False


@pytest.mark.asyncio
async def test_normal_completion_still_works(db_session, monkeypatch):
    """正常完成路径不受取消处理影响：trace completed + 完整回答落库（回归保护）。"""
    await _stubs(monkeypatch)
    fake = QuickGraph()

    async def _get_graph():
        return fake

    monkeypatch.setattr("app.services.chat_service.get_graph", _get_graph)
    user_id, conv_id = await _seed_user_conv(db_session)

    gen = ChatService(db_session).stream_chat(user_id, conv_id, "测试消息")
    events = []
    async for line in gen:
        events.append(json.loads(line))
    # 正常路径：start → token → answer → done（answer/done 由后端终态补充）
    assert [e["event"] for e in events] == ["start", "token", "answer", "done"], events

    msgs = await MessageRepository(db_session).list_by_conversation(conv_id)
    assert [m.role for m in msgs] == ["user", "assistant"], [m.role for m in msgs]
    assert msgs[-1].content == "完整回答", msgs[-1].content
    trace = await TraceRepository(db_session).get(events[0]["trace_id"])
    assert trace.status == "completed", trace.status
    # 正常路径需要保留 current_trace_id（resume/审批定位用）
    conv = await db_session.get(Conversation, conv_id)
    assert conv.current_trace_id == trace.id
