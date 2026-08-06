# backend/app/memory/preferences.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.preference_repo import PreferenceRepository

async def build_context(db: AsyncSession, user_id: str) -> str:
    rows = await PreferenceRepository(db).list_by_user(user_id)
    if not rows:
        return ""
    parts = [f"- ({p.category}) {p.content}" for p in rows]
    return "【个人偏好】\n" + "\n".join(parts)