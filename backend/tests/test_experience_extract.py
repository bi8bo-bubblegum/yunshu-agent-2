# backend/tests/test_experience_extract.py
import pytest
from app.services.experience_svc import (distill_experience, save_personal_experience,
                                         DistillOutput, build_experience_dialog,
                                         DIALOG_MAX_ROUNDS, DIALOG_MAX_CHARS)
from app.models.chat import Message
from app.repositories.conversation_repo import MessageRepository

@pytest.mark.asyncio
async def test_distill_and_save(db_session, monkeypatch):
    class FakeLLM:
        def with_structured_output(self, schema):
            return self
        async def ainvoke(self, prompt):
            return DistillOutput(
                title="国庆大促", summary="满减+直播", content="详情",
                tags=["营销"], event_time=None, result_metrics={"gmv": 320}
            )
    monkeypatch.setattr("app.services.experience_svc.ModelFactory.get_llm", lambda: FakeLLM())
    # pgvector Vector(1536) 列要求 1536 维；被 await 的 stub 必须是 async 函数
    async def _embed(t):
        return [[0.1] * 1536]
    monkeypatch.setattr("app.services.experience_svc.embed_texts", _embed)

    exp = await distill_experience("用户：策划国庆营销方案\n助手：建议满减+直播", user_id="u1", trace_id="t1")
    assert exp is not None
    assert exp.title == "国庆大促"


@pytest.mark.asyncio
async def test_build_dialog_skips_tool_and_keeps_order(db_session):
    """多轮对话构造：跳过 tool 标记消息，只保留 user/assistant，按时间旧→新。"""
    repo = MessageRepository(db_session)
    for role, content in [
        ("user", "第1轮用户问"), ("assistant", "第1轮助手答"),
        ("tool", "工具结果（应被跳过）"),   # tool 标记消息不参与经验判断
        ("user", "第2轮用户问"), ("assistant", "第2轮助手答"),
    ]:
        await repo.add(Message(conversation_id="c1", role=role, content=content))
    await db_session.commit()
    dialog = await build_experience_dialog(db_session, "c1")
    assert "工具结果" not in dialog
    assert dialog == "用户：第1轮用户问\n助手：第1轮助手答\n用户：第2轮用户问\n助手：第2轮助手答"


@pytest.mark.asyncio
async def test_build_dialog_max_rounds(db_session):
    """超过 DIALOG_MAX_ROUNDS 轮时只保留最近 N 轮（最旧轮被丢弃）。"""
    repo = MessageRepository(db_session)
    for i in range(1, DIALOG_MAX_ROUNDS + 3):  # 多出 2 轮，验证窗口裁剪
        await repo.add(Message(conversation_id="c1", role="user", content=f"第{i}轮用户问"))
        await repo.add(Message(conversation_id="c1", role="assistant", content=f"第{i}轮助手答"))
    await db_session.commit()
    dialog = await build_experience_dialog(db_session, "c1")
    # 最早 2 轮应被丢弃，最新一轮保留
    assert "第1轮" not in dialog
    assert "第2轮" not in dialog
    assert f"第{DIALOG_MAX_ROUNDS + 2}轮" in dialog
    assert len(dialog.split("\n")) <= DIALOG_MAX_ROUNDS * 2


@pytest.mark.asyncio
async def test_build_dialog_char_cap(db_session):
    """超长对话截断到 DIALOG_MAX_CHARS，且截断保留最新内容。"""
    repo = MessageRepository(db_session)
    await repo.add(Message(conversation_id="c1", role="user", content="最早的超长上下文" + "甲" * 10000))
    await repo.add(Message(conversation_id="c1", role="assistant", content="最新回复尾巴"))
    await db_session.commit()
    dialog = await build_experience_dialog(db_session, "c1")
    assert len(dialog) <= DIALOG_MAX_CHARS
    assert "最新回复尾巴" in dialog  # 截断取尾部，保留最新内容
