# backend/tests/test_summary.py
import pytest
from app.services.summary import generate_title, maybe_roll_summary

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
