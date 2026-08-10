# backend/app/agents/window.py —— 子图 agent 的「上下文窗口」提取
from langchain_core.messages import BaseMessage


def round_window(messages: list[BaseMessage], max_rounds: int = 2) -> list[BaseMessage]:
    """取「最近 max_rounds 条用户消息之后」的消息窗口（最近 N 轮上下文）。

    子图 ReAct 循环的 messages 包含整个会话历史：所有轮次的 user/assistant 与
    每轮工具调用往返。若全量喂给 LLM，ReAct 多轮后 token 按轮次平方级膨胀。

    窗口语义：保留最近 N 轮的完整上下文（用户诉求 + agent 回复 + 工具数据），
    使 agent 能引用上一轮方案与查询结果，不会多轮失忆（真实事故：只保留最近一条
    human 时，第 2 轮 agent 看不到第 1 轮方案与已查数据，被迫重复查询工具、前后不一致）。
    更早历史由 memory 装配（滚动摘要 + 经验 + 知识库）兜底注入。

    max_rounds=1 退化为旧行为（只保留本轮）。单轮 ReAct（仅 1 条 human）时
    窗口 = 本轮全部往返，行为不变。返回空列表（无用户消息，异常场景）时由
    调用方兜底传全量。
    """
    rounds = 0
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", "") == "human":
            rounds += 1
            if rounds >= max_rounds:
                return messages[i:]
    return messages
