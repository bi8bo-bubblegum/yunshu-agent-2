# backend/app/memory/preferences.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.preference_repo import PreferenceRepository

# 同一偏好至少出现 N 次才视为长期习惯，注入 agent 上下文
MIN_SUPPORT = 2

async def build_context(db: AsyncSession, user_id: str) -> str:
    rows = await PreferenceRepository(db).list_by_user(user_id)
    # 只注入有足够证据（多次出现）的偏好，避免单次表述被当作长期习惯
    stable = [p for p in rows if (p.support_count or 0) >= MIN_SUPPORT]
    if not stable:
        return ""
    parts = [f"- ({p.category}) {p.content}（出现{p.support_count}次）" for p in stable]
    return "【个人偏好】\n" + "\n".join(parts)
