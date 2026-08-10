# backend/tests/test_window.py
"""回归：子图 agent 只喂「本轮上下文窗口」（优化项 3）。

曾长期存在的问题：agent_node 把 messages 全量喂给 LLM——整个会话所有轮次的
user/assistant 与每轮工具往返都重复重发。ReAct 多轮后一条消息塞了几十条
tool message，token 按轮次平方级浪费，且历史内容与 memory 装配注入的
滚动摘要/经验/知识重叠。

修复：只保留「最近一条用户消息之后」的窗口（本轮上下文），更早历史由
memory 装配兜底。
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agents.window import round_window


def test_round_window_only_latest_round():
    """多轮历史：窗口只保留最近一条用户消息之后的内容。"""
    msgs = [
        HumanMessage(content="第一轮"),
        AIMessage(content="第一轮回复"),
        HumanMessage(content="第二轮"),
        AIMessage(content="第二轮回复"),
        ToolMessage(content="工具结果", tool_call_id="t1"),
        AIMessage(content="分析结果"),
    ]
    win = round_window(msgs)
    # 窗口从最后一条 human（第二轮）开始，包含其后的 agent/tool 往返
    assert win == msgs[2:]
    assert [m.content for m in win] == ["第二轮", "第二轮回复", "工具结果", "分析结果"]


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
