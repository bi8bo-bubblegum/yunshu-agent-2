# backend/tests/test_short_term.py
import pytest
from app.models.chat import Conversation, Message
from app.memory.short_term import build_context

@pytest.mark.asyncio
async def test_build_context_summary_only(db_session):
    """最近轮次由 state.messages 提供，短期记忆只输出窗口外滚动摘要。"""
    conv = Conversation(user_id="u1", title="t", summary="早前讨论的压缩摘要")
    db_session.add(conv)
    await db_session.flush()
    for i in range(8):
        db_session.add(Message(conversation_id=conv.id, role="user" if i % 2 == 0 else "assistant", content=f"msg{i}"))
    await db_session.commit()
    context = await build_context(db_session, conv.id)
    assert "压缩摘要" in context
    assert "msg0" not in context and "msg7" not in context


@pytest.mark.asyncio
async def test_build_context_empty_without_summary(db_session):
    """无滚动摘要时返回空（近期原文已由消息通道提供）。"""
    conv = Conversation(user_id="u1", title="t")
    db_session.add(conv)
    await db_session.flush()
    await db_session.commit()
    assert await build_context(db_session, conv.id) == ""
