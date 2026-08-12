# backend/app/agents/window.py —— 子图 agent 的「上下文窗口」提取
from langchain_core.messages import BaseMessage

# 工具返回预算：MCP 工具（query_lines/sales_overview 等）不传筛选参数时返回全量数据，
# 实测可达 25.6MB（query_lines）/ 975KB（sales_overview），单条就远超任何模型上下文窗口
#（真实事故：ChatOpenAI ContextWindowExceededError）。喂给 LLM 前必须按预算截断（浅拷贝，
# 不污染图状态）：
# - 当前轮往返（最近 RECENT_MSG_KEEP 条消息）保留单条上限 MAX_TOOL_CHARS，够 agent 基于
#   样本分析并进一步缩小查询范围（再带 top_n/筛选条件查询）；
# - 历史轮次的工具原始数据已由 agent 消化成回复文本（assistant 是记忆载体，完整保留），
#   只留痕即可，压到 MAX_HIST_TOOL_CHARS。
MAX_TOOL_CHARS = 6000       # 单条工具返回保留上限（当前轮）≈ 1.5K tokens
MAX_HIST_TOOL_CHARS = 1000  # 历史轮次工具返回保留上限 ≈ 0.25K tokens


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

    返回前对窗口内 ToolMessage 做预算截断（见 _bound_tool_window）：工具返回全量数据
    可达几十 MB，必须受控，否则单轮就撑爆上下文窗口。
    """
    rounds = 0
    for i in range(len(messages) - 1, -1, -1):
        if getattr(messages[i], "type", "") == "human":
            rounds += 1
            if rounds >= max_rounds:
                return _bound_tool_window(messages[i:])
    return _bound_tool_window(messages)


def _bound_tool_window(msgs: list[BaseMessage]) -> list[BaseMessage]:
    """窗口内 ToolMessage 内容预算截断（浅拷贝，不污染图状态）。

    只处理 type=="tool" 且 content 为 str 的消息（多模态 list 内容不截断）；
    不超过预算的 tool 消息与所有非 tool 消息原样保留（同一对象，无副作用）。

    当前轮边界 = 最后一条 human 消息之后（本轮用户诉求 + 本轮 ReAct 往返，含 tool_calls
    与工具返回），按 MAX_TOOL_CHARS 保留，保证本轮决策数据不缺失；该 human 之前是历史
    轮次，工具原始数据已由 agent 消化成回复文本，按 MAX_HIST_TOOL_CHARS 只留痕。
    无 human 的异常窗口视为全部当前轮。
    """
    cur_start = 0
    for i in range(len(msgs) - 1, -1, -1):
        if getattr(msgs[i], "type", "") == "human":
            cur_start = i
            break
    out: list[BaseMessage] = []
    for i, m in enumerate(msgs):
        if getattr(m, "type", "") == "tool" and isinstance(m.content, str):
            limit = MAX_TOOL_CHARS if i >= cur_start else MAX_HIST_TOOL_CHARS
            if len(m.content) > limit:
                m = m.model_copy(update={
                    "content": m.content[:limit] + f"\n…[工具结果过长，已截断 {len(m.content)}→{limit} 字符]",
                })
        out.append(m)
    return out
