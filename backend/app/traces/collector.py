# backend/app/traces/collector.py
import asyncio
from datetime import datetime, timezone


class TraceCollector:
    """异步队列采集器：emit 同步入队（队列满直接丢弃，绝不阻塞主流程）；drain 批量取出。"""

    def __init__(self, maxsize: int = 1000):
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)

    def emit(self, trace_id: str, type_: str, payload: dict) -> None:
        """同步内存入队；队列满直接丢弃，绝不阻塞主流程。"""
        try:
            self.queue.put_nowait({
                "trace_id": trace_id, "type": type_, "payload": payload,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        except asyncio.QueueFull:
            pass

    def drain(self) -> list[dict]:
        events = []
        while not self.queue.empty():
            try:
                events.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events


collector = TraceCollector()
