# backend/app/agents/window.py —— 子图 agent 的「上下文窗口」提取
from langchain_core.messages import BaseMessage


def round_window(messages: list[BaseMessage], max_rounds: int = 10) -> list[BaseMessage]:
    """取「最近 max_rounds 条用户消息之后」的消息窗口（最近 N 轮上下文）。

    子图 ReAct 循环的 messages 包含整个会话历史：所有轮次的 user/assistant 与
    每轮工具调用往返。若全量喂给 LLM，ReAct 多轮后 token 按轮次平方级膨胀。

    窗口语义：保留最近 N 轮的完整上下文（用户诉求 + agent 回复 + 工具数据），
    使 agent 能引用之前轮次的答案与已查数据，不会多轮失忆。
    更早历史由 memory 装配（滚动摘要 + 经验 + 知识库）兜底注入。
    即使 agent→done（不回 supervisor），每轮只调用一次 supervisor，
    但同一 agent 的多轮对话仍需引用之前的上下文，max_rounds=10 避免 agent 失忆。
    超出窗口范围的消息由图内 MAX_MESSAGES=100 的裁剪兜底，不会被无限累积。
    """
    rounds = 0
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", "") == "human":
            rounds += 1
            if rounds >= max_rounds:
                return messages[i:]
    return messages
