# backend/app/memory/experiences.py
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.experience_repo import ExperienceRepository
from app.services.embedding import embed_query

# 相关性阈值：低于该相似度的经验视为不相关，不注入上下文，避免硬取 Top5 引入噪声。
# 校准自 text-embedding-3-small 实际分布：余弦相似度整体偏低，强相关查询 Top1 约
# 0.35~0.64，短查询（如「创建」）Top1 仅约 0.21。原 0.3 会把短查询全部滤光，
# 导致「历史经验获取失败」。0.18 在保留相关候选的同时滤掉明显不相关的尾部
#（短查询 Top≈0.21 vs 尾部 0.108；长查询 Top≈0.36 vs 尾部 0.24）。
RELEVANCE_THRESHOLD = 0.18

# 向量召回条数：over-fetch 候选（远超 top_k，供可见性过滤后仍有足够候选）
RECALL_LIMIT = 30


async def build_experience_context(db: AsyncSession, user_id: str, department_id: str | None, query: str, top_k: int = 5) -> str:
    # 第1步：向量召回（over-fetch 30 条候选，直接带相似度分数）
    qv = await embed_query(query)
    candidates = await ExperienceRepository(db).vector_search(qv, RECALL_LIMIT)
    # 第2步：可见范围过滤（personal 仅本人、dept 仅同部门、company 全员）
    visible = []
    for exp, score in candidates:
        if exp.scope == "personal" and exp.owner_id != user_id:
            continue
        if exp.scope == "dept" and (department_id is None or exp.department_id != department_id):
            continue
        visible.append((exp, score))
    if not visible:
        return ""
    # 第3步：同期加权叠加（仅对已相关的经验生效，避免无关经验被抬进上下文）。
    # 候选已按相似度降序返回，无需二次排序。
    now_month = datetime.now().month
    scored = []
    for exp, score in visible:
        final = score
        if exp.event_time and exp.event_time.month == now_month and final >= RELEVANCE_THRESHOLD:
            final += 0.1  # 同期加权（叠加在向量相似度上）
        scored.append((final, exp))
    scored.sort(key=lambda x: -x[0])  # 按最终分数降序（同期加权可能改变顺序）
    selected = [e for score, e in scored if score >= RELEVANCE_THRESHOLD][:top_k]
    if not selected:
        return ""
    parts = [f"- [{e.scope}] {e.title}：{e.summary}（{e.event_time or '无日期'}）" for e in selected]
    return "【相关历史经验】\n" + "\n".join(parts)
