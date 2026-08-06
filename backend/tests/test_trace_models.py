# backend/tests/test_trace_models.py
import pytest
from sqlalchemy import select
from app.models.trace import ExecutionTrace, TraceEvent, Approval
from app.models.configs import McpServer

@pytest.mark.asyncio
async def test_trace_event_flow(db_session):
    trace = ExecutionTrace(user_id="u1", status="running", supervisor_routes=[{"agent": "marketing"}])
    db_session.add(trace)
    await db_session.flush()
    db_session.add(TraceEvent(trace_id=trace.id, type="llm_call", payload={"model": "x", "tokens": 100}))
    db_session.add(Approval(category="tool_call", risk="critical", mode="sync", ref_type="trace",
                            ref_id=trace.id, title="删除文件", context={"path": "/tmp/x"},
                            status="pending", requester_id="u1"))
    await db_session.commit()
    # 不使用 relationship，通过 ref_id 手动查关联
    result = await db_session.get(ExecutionTrace, trace.id)
    assert result.supervisor_routes[0]["agent"] == "marketing"
    events = (await db_session.scalars(
        select(TraceEvent).where(TraceEvent.trace_id == trace.id)
    )).all()
    assert len(events) == 1
    approvals = (await db_session.scalars(
        select(Approval).where(Approval.ref_id == trace.id)
    )).all()
    assert approvals[0].status == "pending"
