# backend/app/memory/assembly.py
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import SessionLocal
from app.memory import short_term, preferences as pref_mem, experiences as exp_mem, knowledge
from app.llm.date_context import current_date_context

logger = logging.getLogger(__name__)

# 经验/知识 RAG 限时：每段各含 embed + rerank（LLM）外部 API，网关慢时单段最坏可挂
# 数分钟（embed timeout=60 + rerank timeout=120）。在 start 事件之后、route 之前执行，
# 挂起会让 SSE 迟迟无 route 事件，前端一直显示「Agent 思考中…」转圈（真实事故：
# start 0.7s 到达后 route 80s+ 未产出）。限时超时降级为空串，主对话正常继续。
RAG_TIMEOUT = 8.0  # 秒：正常 RAG 毫秒级，8s 足够；超时说明外部 API 挂起，丢弃记忆增强


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
            # wait_for 限时：embed/rerank 外部 API 挂起时快速降级，不阻塞 SSE 的 route 事件
            return await asyncio.wait_for(
                exp_mem.build_experience_context(s, user_id, department_id, query),
                timeout=RAG_TIMEOUT,
            )

    async def _kb() -> str:
        async with SessionLocal() as s:
            return await asyncio.wait_for(
                knowledge.retrieve_knowledge(s, query),
                timeout=RAG_TIMEOUT,
            )

    exp_ctx, kb_ctx = await asyncio.gather(_exp(), _kb(), return_exceptions=True)
    # 单段失败（外部 API 超时/异常）降级为空串，不让记忆装配问题拖垮整轮聊天
    for name, ctx in (("经验检索", exp_ctx), ("知识检索", kb_ctx)):
        if not isinstance(ctx, str):
            logger.warning("%s失败（已降级为空）: %s", name, ctx)
    exp_ctx = exp_ctx if isinstance(exp_ctx, str) else ""
    kb_ctx = kb_ctx if isinstance(kb_ctx, str) else ""
    sections = [s for s in (short_ctx, pref_ctx, exp_ctx, kb_ctx) if s]
    body = "\n\n".join(sections)
    return f"{date_line}\n\n{body}" if body else date_line
