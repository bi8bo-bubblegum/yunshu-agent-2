# backend/tests/test_summary.py
import pytest
from app.services.summary import generate_title, maybe_roll_summary, summarize_text
from app.models.chat import Conversation, Message

@pytest.mark.asyncio
async def test_maybe_roll_summary_updates(db_session, monkeypatch):
    from app.models.chat import Conversation
    conv = Conversation(user_id="u1", title="t", summary=None)
    db_session.add(conv)
    await db_session.commit()
    async def fake_summarize(text):
        return "压缩后的摘要"
    monkeypatch.setattr("app.services.summary.summarize_text", fake_summarize)
    await maybe_roll_summary(db_session, conv.id, force=True)
    await db_session.refresh(conv)
    assert conv.summary == "压缩后的摘要"


@pytest.mark.asyncio
async def test_maybe_roll_summary_respects_threshold_and_window(db_session, monkeypatch):
    """阈值行为：未达 max_messages（24 条）不总结；达到则总结且窗口覆盖全部已积累消息
    （修复旧实现「阈值 20 / 窗口 10」的覆盖空洞——最早一批消息永远进不了摘要）。"""
    conv = Conversation(user_id="u2", title="t", summary=None)
    db_session.add(conv)
    await db_session.commit()
    for i in range(23):  # 23 条 < 阈值 24 → 不应触发
        db_session.add(Message(conversation_id=conv.id, role="user" if i % 2 == 0 else "assistant",
                               content=f"消息{i}"))
    await db_session.commit()

    captured = {}

    async def fake_summarize(text):
        captured["text"] = text
        return "滚动摘要"

    monkeypatch.setattr("app.services.summary.summarize_text", fake_summarize)
    await maybe_roll_summary(db_session, conv.id)
    assert conv.summary is None, "23 条未达阈值，不应总结"

    # 第 24 条到达阈值 → 触发，且窗口 = max_messages，覆盖全部已积累消息（无覆盖空洞）
    db_session.add(Message(conversation_id=conv.id, role="user", content="消息23"))
    await db_session.commit()
    await maybe_roll_summary(db_session, conv.id)
    await db_session.refresh(conv)
    assert conv.summary == "滚动摘要"
    # 窗口内应包含全部 24 条消息文本（最早的消息0 不被遗漏）
    assert "消息0" in captured["text"]
    assert "消息23" in captured["text"]
    assert captured["text"].count("消息") >= 24


@pytest.mark.asyncio
async def test_summarize_text_calls_llm(monkeypatch):
    """summarize_text 调用摘要 LLM（结构化输出 SummaryOutput）。"""
    class _LLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, prompt):
            return type("R", (), {"summary": "压缩摘要"})()
    monkeypatch.setattr("app.services.summary.ModelFactory.get_llm", lambda k=None: _LLM())
    assert await summarize_text("用户：你好\n助手：你好呀") == "压缩摘要"


class _FailingTitleLLM:
    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, prompt):
        raise ValueError("parse error")


@pytest.mark.asyncio
async def test_generate_title_fallback_on_llm_failure(monkeypatch):
    """标题生成 LLM 全部失败时，兜底取消息前 20 字，保证不再是默认标题。"""
    monkeypatch.setattr("app.services.summary.ModelFactory.get_llm", lambda k=None: _FailingTitleLLM())
    title = await generate_title("查询我的营收情况，给出异常营收提醒和建议")
    assert title == "查询我的营收情况，给出异常营收提醒和建议"


class _EmptyTitleLLM:
    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, prompt):
        return type("T", (), {"title": "   "})()


@pytest.mark.asyncio
async def test_generate_title_fallback_on_empty(monkeypatch):
    """LLM 返回空标题时同样走兜底。"""
    monkeypatch.setattr("app.services.summary.ModelFactory.get_llm", lambda k=None: _EmptyTitleLLM())
    title = await generate_title("你好，帮我看看排班")
    assert title == "你好，帮我看看排班"
