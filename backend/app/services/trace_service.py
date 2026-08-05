# backend/app/services/trace_service.py —— 监测查询业务（只组合 repo，不直查 DB）
from app.models.trace import TraceEvent
from app.repositories.trace_repo import TraceRepository, EventRepository


class TraceService:
    def __init__(self, db):
        self.trace_repo = TraceRepository(db)
        self.event_repo = EventRepository(db)

    async def list_by_user(self, user_id: str, limit: int = 50):
        return await self.trace_repo.list_by_user(user_id, limit)

    async def events(self, trace_id: str) -> list[TraceEvent]:
        return await self.event_repo.list_by_trace(trace_id)
