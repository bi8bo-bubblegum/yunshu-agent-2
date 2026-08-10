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


@pytest.mark.asyncio
async def test_done_node_skips_blank_ai_message(monkeypatch):
    """done_node 选取最终回复时必须跳过纯空白 AI 消息（如 '\n\n'）。

    真实事故：marketing→scheduling 协作轮，scheduling 的 ReAct 最后一步 LLM 输出
    '\n\n'（空白过渡文本）写入 messages，done_node 用 if c（不过滤空白）把它当
    最终回复，agent_response='\n\n'；落库时 segments 最后一段（有实质内容的
    scheduling）被空白 agent_response 覆盖，前端气泡空白、内容全在「查看执行步骤」。
    修复后 agent_response 应为最后一条有实质内容的 AI 消息，跳过空白。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    async def fake_route(message, agents):
        return {"agent": "done", "reason": "测试直接结束", "confidence": 0.9}

    monkeypatch.setattr("app.agents.graph.route_decision", fake_route)
    g = await get_graph()
    result = await g.ainvoke(
        {
            "user_message": "结合天气策划活动",
            "memory_context": "",
            "messages": [
                HumanMessage(content="结合天气策划活动"),
                AIMessage(content="这是营销方案的实质内容"),
                AIMessage(content="\n\n"),  # scheduling 的空白过渡输出，应被跳过
            ],
        },
        config={"configurable": {"thread_id": "graph-done-blank-test"}},
    )
    assert result["agent_response"] == "这是营销方案的实质内容"
