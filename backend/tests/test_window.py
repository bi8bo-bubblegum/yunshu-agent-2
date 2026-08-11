# backend/tests/test_window.py
"""回归：子图 agent 的上下文窗口（最近 max_rounds=10 轮）。

曾长期存在的问题：agent_node 把 messages 全量喂给 LLM——整个会话所有轮次的
user/assistant 与每轮工具往返都重复重发。ReAct 多轮后一条消息塞了几十条
tool message，token 按轮次平方级浪费。

修复演进：
1. 第一版只保留「最近一条用户消息之后」→ 多轮失忆（真实事故：第 2 轮看不到第 1
   轮方案，被迫重复查询工具）
2. 演进为 max_rounds=2 → agent 能看到上一轮方案与查询结果，不会多轮失忆
3. 提升为 max_rounds=10 → 保留最近 10 轮完整上下文，agent 能引用更早的对话
4. 更早历史由 memory 装配（滚动摘要+经验+知识库）兜底
5. 超出窗口范围的消息由图内 MAX_MESSAGES=100 的裁剪兜底，不会被无限累积
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.window import round_window


def test_round_window_keeps_recent_rounds():
    """三轮历史：默认 max_rounds=10，3 轮全在窗口内，全部保留。"""
    msgs = [
        HumanMessage(content="第一轮"),
        AIMessage(content="第一轮回复"),
        ToolMessage(content="第一轮工具", tool_call_id="t1"),
        HumanMessage(content="第二轮"),
        AIMessage(content="第二轮回复"),
        HumanMessage(content="第三轮"),
        AIMessage(content="第三轮回复"),
    ]
    win = round_window(msgs)
    assert win == msgs
    assert [m.content for m in win] == ["第一轮", "第一轮回复", "第一轮工具",
                                         "第二轮", "第二轮回复", "第三轮", "第三轮回复"]


def test_round_window_two_rounds_keeps_both():
    """恰好 2 轮：窗口保留全部（两轮都在窗口内）。"""
    msgs = [
        HumanMessage(content="第一轮"),
        AIMessage(content="第一轮回复"),
        HumanMessage(content="第二轮"),
        AIMessage(content="第二轮回复"),
        ToolMessage(content="工具结果", tool_call_id="t1"),
        AIMessage(content="分析结果"),
    ]
    assert round_window(msgs) == msgs


def test_round_window_single_round_reaction():
    """单轮 ReAct（human + ai(tool) + tool + ai）：窗口保留全部（本轮内工具往返）。"""
    msgs = [
        HumanMessage(content="查一下数据"),
        AIMessage(content="", tool_calls=[{"name": "query_sales", "args": {}, "id": "1"}]),
        ToolMessage(content="数据", tool_call_id="1"),
        AIMessage(content="分析结果"),
    ]
    assert round_window(msgs) == msgs


def test_round_window_no_human_returns_all():
    """无用户消息（异常/纯工具场景）：返回全量，调用方兜底。"""
    msgs = [AIMessage(content="a"), ToolMessage(content="t", tool_call_id="x")]
    assert round_window(msgs) == msgs


def test_round_window_max_rounds_one_locks_old_behavior():
    """max_rounds=1：锁定旧行为，只保留最近一条 human 之后的窗口。"""
    msgs = [
        HumanMessage(content="第一轮"),
        AIMessage(content="第一轮回复"),
        HumanMessage(content="第二轮"),
        AIMessage(content="第二轮回复"),
    ]
    assert round_window(msgs, max_rounds=1) == msgs[2:]


def test_round_window_default_keeps_all_under_10():
    """默认 max_rounds=10：10 轮以内全保留。"""
    msgs = [HumanMessage(content=f"第{i}轮") for i in range(1, 11)]
    win = round_window(msgs)
    assert win == msgs


def test_round_window_truncates_beyond_10():
    """超过 10 轮时裁掉最早的消息，只保留最近 10 轮。"""
    msgs = [HumanMessage(content=f"第{i}轮") for i in range(1, 16)]  # 15 轮
    win = round_window(msgs)
    # 最近 10 轮 = 从第 6 轮起（16 - 10 = 6）
    assert len(win) == 10
    assert win[0].content == "第6轮"
    assert win[-1].content == "第15轮"