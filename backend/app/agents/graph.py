from langgraph.graph import StateGraph, END

from app.agents.state import AgentState


def build_graph():
    g = StateGraph(AgentState)
    async def echo_node(state: AgentState):
        return {"agent_response": f"收到：{state.get('user_message', '')}"}
    g.add_node("echo",echo_node)
    g.set_entry_point("echo")
    g.add_edge("echo", END)
    return g.compile()

graph = build_graph()

