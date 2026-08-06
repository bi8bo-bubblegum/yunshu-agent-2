# backend/tests/test_short_term.py
import pytest
from app.models.chat import Conversation, Message
from app.memory.short_term import build_context

@pytest.mark.asyncio
async def test_build_context_recent_n(db_session):
    conv = Conversation(user_id="u1", title="t")
    db_session.add(conv)
    await db_session.flush()
    for i in range(8):
        db_session.add(Message(conversation_id=conv.id, role="user" if i % 2 == 0 else "assistant", content=f"msg{i}"))
    await db_session.commit()
    context = await build_context(db_session, conv.id, recent_rounds=3)
    assert "msg7" in context
    assert "msg0" not in context
