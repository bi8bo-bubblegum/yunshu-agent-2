# backend/tests/test_summary.py
import pytest
from app.services.summary import maybe_roll_summary

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
