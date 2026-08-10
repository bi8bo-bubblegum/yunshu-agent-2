# backend/tests/test_window.py
"""回归：子图 agent 只喂「最近 N 轮上下文窗口」（优化项 3 演进）。

曾长期存在的问题：agent_node 把 messages 全量喂给 LLM——整个会话所有轮次的
user/assistant 与每轮工具往返都重复重发。ReAct 多轮后一条消息塞了几十条
tool message，token 按轮次平方级浪费，且历史内容与 memory 装配注入的
滚动摘要/经验/知识重叠。

第一版修复只保留「最近一条用户消息之后」的窗口，导致多轮失忆：第 2 轮 agent
看不到第 1 轮的方案与已查工具数据，被迫重复查询工具、前后不一致（真实事故）。
演进为保留最近 max_rounds 轮（默认 2 轮），更早历史由 memory 装配兜底。
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.window import round_window


def test_round_window_keeps_recent_two_rounds():
    """三轮历史：窗口保留最近 2 轮（从倒数第 2 条 human 起），更早的第 1 轮裁掉。"""
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
    # 最近 2 条 human 是第二轮、第三轮，窗口从第二轮 human 起保留
    assert win == msgs[3:]
    assert [m.content for m in win] == ["第二轮", "第二轮回复", "第三轮", "第三轮回复"]


def test_round_window_two_rounds_keeps_all():
    """恰好 2 轮：全部保留（都在最近 2 轮窗口内）。"""
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


def test_round_window_max_rounds_one_is_legacy():
    """max_rounds=1 退化为旧行为：只保留最近一条 human 之后的窗口。"""
    msgs = [
        HumanMessage(content="第一轮"),
        AIMessage(content="第一轮回复"),
        HumanMessage(content="第二轮"),
        AIMessage(content="第二轮回复"),
    ]
    assert round_window(msgs, max_rounds=1) == msgs[2:]
