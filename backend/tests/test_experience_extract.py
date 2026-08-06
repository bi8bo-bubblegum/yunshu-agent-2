# backend/tests/test_experience_extract.py
import pytest
from app.services.experience_svc import distill_experience, save_personal_experience, DistillOutput

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
