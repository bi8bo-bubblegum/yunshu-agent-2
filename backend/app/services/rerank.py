# backend/app/services/rerank.py
from pydantic import BaseModel, Field
from app.llm.factory import ModelFactory

class RerankItem(BaseModel):
    """单条候选相关性评分"""
    score: float = Field(description="相关性评分 0~1")
    reason: str = Field(description="评分理由")

class RerankOutput(BaseModel):
    """rerank 结构化输出"""
    items: list[RerankItem] = Field(description="与输入candidates顺序一致的评分列表")

async def rerank(query: str, candidates: list[str]) -> list[float]:
    """LLM 对每条候选打分，返回与 candidates 等长的分数列表（0~1，越高越相关）。
    两阶段检索：向量 over-fetch → rerank 精排 → 截断 top_k。"""
    if not candidates:
        return []
    llm = ModelFactory.get_llm().with_structured_output(RerankOutput)
    numbered = "\n".join(f"{i}. {c[:500]}" for i, c in enumerate(candidates))
    result = await llm.ainvoke(
        f"根据用户问题对以下候选内容逐一打分（0~1，越高越相关）。\n"
        f"问题：{query}\n候选：\n{numbered}"
    )
    return [item.score for item in result.items]