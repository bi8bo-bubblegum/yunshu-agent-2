# backend/app/traces/writer.py —— 后台批量落库任务
import asyncio
import logging

from sqlalchemy import insert

from app.core.database import SessionLocal
from app.models.trace import TraceEvent
from app.traces.collector import collector

logger = logging.getLogger(__name__)


async def trace_writer_loop(interval: float = 1.0, batch: int = 100) -> None:
    """定时从队列 drain 事件，批量插入 trace_events 表。
    异常降级：业务不中断，失败事件直接丢弃（仅记录日志）。"""
    while True:
        await asyncio.sleep(interval)
        events = collector.drain()
        if not events:
            continue
        for i in range(0, len(events), batch):
            chunk = events[i:i + batch]
            try:
                async with SessionLocal() as db:
                    await db.execute(insert(TraceEvent), chunk)
                    await db.commit()
            except Exception as e:
                logger.warning("trace writer 批量落库失败（已降级丢弃 %d 条）: %s", len(chunk), e)
