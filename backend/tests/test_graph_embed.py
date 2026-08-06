# backend/tests/test_graph_embed.py
import pytest
from langchain_core.messages import AIMessage
from app.agents.graph import get_graph


class FakeLLM:
    def bind_tools(self, tools):
        self._tools = tools
        return self

    async def ainvoke(self, messages):
        if len(messages) == 2:
            return AIMessage(content="", tool_calls=[{
                "name": "query_marketing_campaigns", "args": {"status": "active"}, "id": "c1", "type": "tool_call",
            }])
        return AIMessage(content="营销方案已生成")


@pytest.mark.asyncio
async def test_main_graph_contains_subagent_nodes():
    """父图节点应包含 supervisor、各子 agent 子图与 done。"""
    g = await get_graph()
    nodes = set(g.get_graph().nodes)
    assert {"supervisor", "marketing", "sales_analysis", "scheduling", "done"} <= nodes


@pytest.mark.asyncio
async def test_end_to_end_route_and_respond(monkeypatch):
    """端到端：supervisor 路由到营销子图 → 子图内 ReAct 调用工具 → 最终回答。"""
    async def fake_route(message, agents):
        return {"agent": "marketing", "reason": "营销策划", "confidence": 0.9}
    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)
    monkeypatch.setattr("app.agents.marketing.agent.ModelFactory.get_llm", lambda key: FakeLLM())
    g = await get_graph()
    result = await g.ainvoke(
        {"user_message": "策划国庆营销", "memory_context": "", "messages": []},
        config={"configurable": {"thread_id": "graph-embed-test"}},
    )
    assert result["agent_response"]
