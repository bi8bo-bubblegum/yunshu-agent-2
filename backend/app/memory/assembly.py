# backend/app/memory/assembly.py
import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import SessionLocal
from app.memory import short_term, preferences as pref_mem, experiences as exp_mem
from app.llm.date_context import current_date_context

logger = logging.getLogger(__name__)

# 经验 RAG 限时：经验段含 embed 外部 API + 向量检索。去掉 rerank LLM 打分后
#（rerank 慢到单段 25s，8s 限时下必超时 → 经验永远获取失败），正常耗时约 1s。
# 限时是防外部 API 挂起的降级保护（embed timeout=60），超时丢弃记忆增强，主对话正常继续。
# 注：知识库已改 agent 主动调用的 search_knowledge 工具（见 tools/builtin），不再自动装配。
RAG_TIMEOUT = 8.0  # 秒：正常经验 RAG 约 1s，8s 足够；超时说明外部 API 挂起，丢弃记忆增强


async def assemble_memory(
    db: AsyncSession, user_id: str, conversation_id: str,
    department_id: str | None, query: str,
) -> str:
    # 所有 agent 共用同一段记忆上下文：顶部注入当前日期，避免模型日期幻觉
    date_line = current_date_context()
    # 轻量段（本地 DB 查询，毫秒级）用请求级 db 串行执行。
    # 经验 RAG（含 embed 外部 API + 向量检索）开独立 session 执行——
    # AsyncSession 官方不支持同实例并发，并行必须独立连接。
    short_ctx = await short_term.build_context(db, conversation_id)
    pref_ctx = await pref_mem.build_context(db, user_id)
    exp_ctx = await _build_exp(user_id, department_id, query)
    sections = [s for s in (short_ctx, pref_ctx, exp_ctx) if s]
    body = "\n\n".join(sections)
    return f"{date_line}\n\n{body}" if body else date_line


async def _build_exp(user_id: str, department_id: str | None, query: str) -> str:
    async with SessionLocal() as s:
        # wait_for 限时：embed 外部 API 挂起时快速降级，不阻塞 SSE 的 route 事件
        try:
            return await asyncio.wait_for(
                exp_mem.build_experience_context(s, user_id, department_id, query),
                timeout=RAG_TIMEOUT,
            )
        except Exception as e:
            logger.warning("经验检索失败（已降级为空）: %s", e)
            return ""
