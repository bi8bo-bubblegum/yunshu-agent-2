# backend/app/api/traces.py —— 薄路由：监测查询 API
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_user
from app.models.org import User
from app.services.trace_service import TraceService

router = APIRouter(prefix="/api/traces", tags=["traces"])


def get_trace_service(db: AsyncSession = Depends(get_db)) -> TraceService:
    return TraceService(db)


@router.get("")
async def list_traces(svc: TraceService = Depends(get_trace_service),
                      user: User = Depends(get_current_user)):
    rows = await svc.list_by_user(user.id)
    return [{"id": t.id, "status": t.status, "conversation_id": t.conversation_id,
             "supervisor_routes": t.supervisor_routes} for t in rows]


@router.get("/{trace_id}/events")
async def trace_events(trace_id: str, svc: TraceService = Depends(get_trace_service),
                       _: User = Depends(get_current_user)):
    return [{"type": e.type, "payload": e.payload, "created_at": e.created_at}
            for e in await svc.events(trace_id)]
