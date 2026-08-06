# backend/tests/test_chat_models.py
import pytest
from sqlalchemy import select
from app.models.chat import Conversation, Message
from app.models.org import User

@pytest.mark.asyncio
async def test_conversation_with_messages(db_session):
    user = User(username="bob", password_hash="x", display_name="Bob")
    db_session.add(user)
    await db_session.flush()
    conv = Conversation(user_id=user.id, title="国庆营销")
    db_session.add(conv)
    await db_session.flush()
    db_session.add(Message(conversation_id=conv.id, role="user", content="策划国庆方案"))
    await db_session.commit()
    # 不使用 relationship，通过 conversation_id 手动查消息
    result = await db_session.get(Conversation, conv.id)
    messages = (await db_session.scalars(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    )).all()
    assert len(messages) == 1
    assert messages[0].role == "user"
