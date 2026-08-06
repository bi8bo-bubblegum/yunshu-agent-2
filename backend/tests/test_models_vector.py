# backend/tests/test_models_vector.py
import pytest
from datetime import date
from sqlalchemy import select
from app.models.experience import Experience
from app.models.knowledge import Document, Chunk

@pytest.mark.asyncio
async def test_experience_with_embedding(db_session):
    # pgvector Vector(1536) 列要求 1536 维
    vec = [0.1] * 1536
    exp = Experience(
        owner_id="u1", scope="personal", status="approved",
        title="国庆大促策略", summary="满减+直播", content="详情",
        event_time=date(2025, 10, 1), result_metrics={"gmv": 320, "roi": 3.2},
        embedding=vec,
    )
    db_session.add(exp)
    await db_session.commit()
    result = await db_session.scalar(select(Experience))
    assert result.title == "国庆大促策略"
    assert result.result_metrics["gmv"] == 320
