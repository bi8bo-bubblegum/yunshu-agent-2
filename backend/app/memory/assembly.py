# backend/app/memory/assembly.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.memory import short_term, preferences as pref_mem, experiences as exp_mem, knowledge
from app.llm.date_context import current_date_context

async def assemble_memory(
    db: AsyncSession, user_id: str, conversation_id: str,
    department_id: str | None, query: str,
) -> str:
    # 所有 agent 共用同一段记忆上下文：顶部注入当前日期，避免模型日期幻觉
    date_line = current_date_context()
    sections = []
    sections.append(await short_term.build_context(db, conversation_id))
    sections.append(await pref_mem.build_context(db, user_id))
    sections.append(await exp_mem.build_experience_context(db, user_id, department_id, query))
    sections.append(await knowledge.retrieve_knowledge(db, query))
    body = "\n\n".join(s for s in sections if s)
    return f"{date_line}\n\n{body}" if body else date_line
