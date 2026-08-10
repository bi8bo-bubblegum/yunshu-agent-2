# backend/app/memory/assembly.py
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import SessionLocal
from app.memory import short_term, preferences as pref_mem, experiences as exp_mem, knowledge
from app.llm.date_context import current_date_context

logger = logging.getLogger(__name__)


async def assemble_memory(
    db: AsyncSession, user_id: str, conversation_id: str,
    department_id: str | None, query: str,
) -> str:
    # 所有 agent 共用同一段记忆上下文：顶部注入当前日期，避免模型日期幻觉
    date_line = current_date_context()
    # 轻量段（本地 DB 查询，毫秒级）用请求级 db 串行执行。
    # 重量段（经验 RAG / 知识 RAG，各含 embed + rerank 外部 API，最耗时）各自开
    # 独立 session 并行执行——AsyncSession 官方不支持同实例并发，并行必须独立连接。
    short_ctx = await short_term.build_context(db, conversation_id)
    pref_ctx = await pref_mem.build_context(db, user_id)

    async def _exp() -> str:
        async with SessionLocal() as s:
            return await exp_mem.build_experience_context(s, user_id, department_id, query)

    async def _kb() -> str:
        async with SessionLocal() as s:
            return await knowledge.retrieve_knowledge(s, query)

    exp_ctx, kb_ctx = await asyncio.gather(_exp(), _kb(), return_exceptions=True)
    # 单段失败（如外部 API 超时）降级为空串，不让记忆装配问题拖垮整轮聊天
    for name, ctx in (("经验检索", exp_ctx), ("知识检索", kb_ctx)):
        if not isinstance(ctx, str):
            logger.warning("%s失败（已降级为空）: %s", name, ctx)
    exp_ctx = exp_ctx if isinstance(exp_ctx, str) else ""
    kb_ctx = kb_ctx if isinstance(kb_ctx, str) else ""
    sections = [s for s in (short_ctx, pref_ctx, exp_ctx, kb_ctx) if s]
    body = "\n\n".join(sections)
    return f"{date_line}\n\n{body}" if body else date_line
