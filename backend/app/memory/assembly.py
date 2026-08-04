# backend/app/memory/assembly.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.memory import short_term, preferences as pref_mem, experiences as exp_mem, knowledge

async def assemble_memory(
    db: AsyncSession, user_id: str, conversation_id: str,
    department_id: str | None, query: str,
) -> str:
    sections = []
    sections.append(await short_term.build_context(db, conversation_id))
    sections.append(await pref_mem.build_context(db, user_id))
    sections.append(await exp_mem.build_experience_context(db, user_id, department_id, query))
    sections.append(await knowledge.retrieve_knowledge(db, query))
    return "\n\n".join(s for s in sections if s)