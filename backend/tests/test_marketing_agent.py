# backend/tests/test_marketing_agent.py
import pytest
from langchain_core.messages import AIMessage
from app.agents.marketing.agent import build_marketing_agent, TOOL_NAMES, MAX_TOOL_ROUNDS

@pytest.mark.asyncio
async def test_marketing_agent_subgraph(db_session):
    """营销助手模块声明自己的工具并构建编译子图（供父图嵌入）。"""
    assert TOOL_NAMES == ["query_marketing_campaigns", "create_marketing_campaign", "publish_campaign"]
    assert await build_marketing_agent(db_session) is not None

@pytest.mark.asyncio
async def test_marketing_subgraph_stops_after_max_rounds(db_session, monkeypatch):
    """LLM 持续要求调用工具时，子图在 MAX_TOOL_ROUNDS 后强制结束，不抛异常。"""
    class LoopLLM:
        def bind_tools(self, tools):
            return self
        async def ainvoke(self, messages):
            return AIMessage(content="", tool_calls=[{
                "name": "query_marketing_campaigns", "args": {"status": "active"}, "id": f"c{len(messages)}", "type": "tool_call",
            }])

    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda k: LoopLLM())
    g = await build_marketing_agent(db_session)
    result = await g.ainvoke({"user_message": "循环", "memory_context": "", "messages": []})
    assert result["tool_rounds"] == MAX_TOOL_ROUNDS  # 达到上限强制结束
