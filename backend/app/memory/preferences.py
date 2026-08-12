# backend/app/memory/preferences.py
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.preference_repo import PreferenceRepository

# 注入预算：偏好累积无上限会导致每个 agent 的 SYSTEM 提示上下文膨胀。
# Top-N 条数 + 字符预算双保险，注入恒有界；排序按「新鲜 × confidence」，
# 新确认的偏好自然前移、旧偏好按时间淡出（软性演化，零误删）。
MAX_PREFS = 10        # 注入条数上限（中文偏好平均 ~54 字符，10 条 ≈ 600 字符）
MAX_PREF_CHARS = 600  # 字符预算硬兜底（近似 token 预算）

async def build_context(db: AsyncSession, user_id: str) -> str:
    rows = await PreferenceRepository(db).list_by_user_ranked(user_id, limit=MAX_PREFS)
    if not rows:
        return ""
    parts: list[str] = []
    used = 0
    for p in rows:
        item = f"- ({p.category}) {p.content}"
        if used and used + len(item) > MAX_PREF_CHARS:
            break
        parts.append(item)
        used += len(item) + 1
    return "【个人偏好】\n" + "\n".join(parts)