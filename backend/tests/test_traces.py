# backend/tests/test_traces.py
"""任务 34：留痕采集器单测（不依赖数据库，仅验证队列行为）。
注：TraceCollector 的 emit/drain 均为同步方法，测试无需 async。"""
from app.traces.collector import TraceCollector


def test_collector_emit_and_drain():
    collector = TraceCollector()
    collector.emit("t1", "llm_call", {"model": "x"})
    assert collector.queue.qsize() == 1
    events = collector.drain()
    assert len(events) == 1 and events[0]["type"] == "llm_call"


def test_collector_drop_on_full():
    c = TraceCollector(maxsize=2)
    c.emit("t", "a", {})
    c.emit("t", "b", {})
    c.emit("t", "c", {})  # 满时丢弃，不阻塞
    assert c.queue.qsize() == 2
