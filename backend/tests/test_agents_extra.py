# backend/tests/test_agents_extra.py
import pytest
from langchain_core.messages import AIMessage
from app.agents.sales_analysis.agent import build_sales_agent, TOOL_NAMES as SALES_TOOLS, MAX_TOOL_ROUNDS
from app.agents.scheduling.agent import build_scheduling_agent, TOOL_NAMES as SCHEDULING_TOOLS

@pytest.mark.asyncio
async def test_sales_agent_subgraph(db_session):
    assert SALES_TOOLS == ["query_sales_data", "delete_order"]
    assert await build_sales_agent(db_session) is not None

@pytest.mark.asyncio
async def test_scheduling_agent_subgraph(db_session):
    assert SCHEDULING_TOOLS == ["query_schedule", "adjust_schedule"]
    assert await build_scheduling_agent(db_session) is not None

@pytest.mark.asyncio
async def test_sales_subgraph_stops_after_max_rounds(db_session, monkeypatch):
    """经营分析子图同样具备工具轮次上限保护。"""
    class LoopLLM:
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, messages):
            return AIMessage(content="", tool_calls=[{
                "name": "query_sales_data", "args": {"metric": "revenue", "period": "7d"}, "id": f"c{len(messages)}", "type": "tool_call",
            }])

    monkeypatch.setattr("app.agents.sales_analysis.agent.ModelFactory.get_llm", lambda k: LoopLLM())
    g = await build_sales_agent(db_session)
    result = await g.ainvoke({"user_message": "循环", "memory_context": "", "messages": []})
    assert result["tool_rounds"] == MAX_TOOL_ROUNDS
