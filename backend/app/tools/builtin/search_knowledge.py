import asyncio
from pydantic import BaseModel, Field

from app.core.database import SessionLocal
from app.memory.knowledge import search_chunks

# 知识检索限时：embed + rerank 为外部 LLM 调用，网关慢时单次最坏可挂分钟级。
# 工具由 agent 主动调用，挂起会卡住 ReAct 循环（agent 等工具返回），限时超时降级
# 返回空结果 + 提示，不让外部 API 问题拖垮整轮对话。
KB_SEARCH_TIMEOUT = 8.0  # 秒：正常检索毫秒级，8s 足够；超时说明外部 API 挂起

class SearchKnowledgeArgs(BaseModel):
    query: str = Field(description="知识检索查询语句：用自然语言描述想了解的知识主题，"
                                    "如「公司报销制度」「员工病假规定」「开发票流程」。必填。")
    top_k: int = Field(5, description="返回相关知识条数上限（默认 5）。")

DESCRIPTION = (
    "检索企业知识库（企业制度、法律法规、政策、流程、公告等外部知识），返回相关知识片段及其来源文档，"
    "为回答提供有据可依的外部依据。\n"
    "【何时调用】用户询问企业制度、法律法规、政策规定、办事流程、报销/请假/薪酬等规则时；"
    "回答需要引用公司规范或外部法律依据时。\n"
    "【何时不调用】营销策划、销售数据分析、排班调度等业务操作类问题（应调用对应业务工具）；"
    "用户只是闲聊或询问已有活动/数据时。\n"
    "【调用示例】\n"
    "- 「公司的报销制度是怎样的」→ query=公司报销制度\n"
    "- 「员工请病假有什么规定」→ query=员工病假规定\n"
    "- 「我们开票要走什么流程」→ query=开发票流程"
)

async def search_knowledge(query: str, top_k: int = 5) -> dict:
    """语义检索知识库，返回相关知识片段（来源文档 + 内容）。

    embed/rerank 为外部 LLM 调用，限时降级避免外部 API 挂起卡住 agent。"""
    try:
        async with SessionLocal() as db:
            hits = await asyncio.wait_for(search_chunks(db, query, top_k),
                                          timeout=KB_SEARCH_TIMEOUT)
    except asyncio.TimeoutError:
        return {"results": [], "count": 0,
                "error": "知识库检索超时，可能暂无匹配内容，请稍后重试或咨询管理员"}
    return {"results": [{"document_id": h["document_id"], "content": h["content"]}
                        for h in hits],
            "count": len(hits)}
