from typing import TypedDict, Annotated
from operator import add

from langchain_core.messages import BaseMessage


class AgentState(TypedDict, total=False):
    conversation_id: str
    user_id: str
    user_message: str
    history: str
    memory_context: str
    messages: Annotated[list[BaseMessage], add]
    tool_rounds: Annotated[int, add]
    agent_response: str
    route_history: Annotated[list[str], add]
    pending_agent: str
    hitl_decision: str | None
    trace_id: str