# backend/app/agents/window.py —— 子图 agent 的「本轮上下文窗口」提取
from langchain_core.messages import BaseMessage


def round_window(messages: list[BaseMessage]) -> list[BaseMessage]:
    """取「最近一条用户消息之后」的消息窗口（本轮上下文）。

    子图 ReAct 循环的 messages 包含整个会话历史：所有轮次的 user/assistant 与
    每轮工具调用往返。若全量喂给 LLM，ReAct 多轮后 token 按轮次平方级膨胀。
    这里只保留本轮用户消息及其后的 agent/tool 往返（当前 ReAct 进度），
    更早历史由 memory 装配（滚动摘要 + 经验 + 知识库）兜底注入。

    返回空列表（无用户消息，异常场景）时由调用方兜底传全量。
    """
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", "") == "human":
            return messages[i:]
    return messages
