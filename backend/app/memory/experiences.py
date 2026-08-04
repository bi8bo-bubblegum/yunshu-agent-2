# backend/app/memory/experiences.py
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.experience_repo import ExperienceRepository
from app.services.embedding import embed_query
from app.services.rerank import rerank

async def build_experience_context(db: AsyncSession, user_id: str, department_id: str | None, query: str, top_k: int = 5) -> str:
    # 第1步：向量召回（over-fetch 30条候选）
    qv = await embed_query(query)
    candidates = await ExperienceRepository(db).vector_search(qv, 30)
    # 第2步：可见范围过滤（先过滤再 rerank，减少 LLM 打分数量）
    visible = []
    for exp in candidates:
        if exp.scope == "personal" and exp.owner_id != user_id:
            continue
        if exp.scope == "dept" and (department_id is None or exp.department_id != department_id):
            continue
        visible.append(exp)
    if not visible:
        return ""
    # 第3步：rerank 精排（LLM 对每条候选打分）
    texts = [f"{e.title} {e.summary}" for e in visible]
    scores = await rerank(query, texts)
    # 第4步：同期加权叠加
    now_month = datetime.now().month
    scored = []
    for i, exp in enumerate(visible):
        final = scores[i]
        if exp.event_time and exp.event_time.month == now_month:
            final += 0.1  # 同期加权（叠加在 rerank 分数上）
        scored.append((final, exp))
    scored.sort(key=lambda x: -x[0])  # 按最终分数降序
    selected = [e for _, e in scored[:top_k]]
    if not selected:
        return ""
    parts = [f"- [{e.scope}] {e.title}：{e.summary}（{e.event_time or '无日期'}）" for e in selected]
    return "【相关历史经验】\n" + "\n".join(parts)