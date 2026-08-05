from typing import TypedDict, Annotated
from operator import add

from langchain_core.messages import BaseMessage


class AgentState(TypedDict, total=False):
    conversation_id: str
    user_id: str
    user_message: str
    history: str
    memory_context: str          # 记忆装配结果
    messages: Annotated[list[BaseMessage], add]  # 子图 ReAct 循环的工作消息
    tool_rounds: Annotated[int, add]             # 子图工具调用轮次计数（防死循环）
    agent_response: str
    route_history: Annotated[list[str], add]  # 已路由过的 agent，防死循环
    pending_agent: str           # supervisor 本次路由目标
    approval_result: dict | None  # 审批结果（critical 工具调用恢复时携带）
    trace_id: str
