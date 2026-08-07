from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import settings

# best-2-openai 网关不支持 response_format（结构化输出），导致 with_structured_output
# 每次解析失败 → 路由走关键词兜底 → 永不 done、多轮错乱。best-1 实测结构化输出正常。
MODEL_MAP = {
    "default": "best-1",
    "marketing": "best-1",
    "sales_analysis": "best-1",
    "scheduling": "best-1"
}

class ModelFactory:
    @classmethod
    def get_llm(cls, model_key: str = "default"):
        return ChatOpenAI(
            model=MODEL_MAP[model_key],
            base_url=settings.MODEL_API_BASE,
            api_key=settings.MODEL_API_KEY,
            temperature=0.3,
            # 网关偶发挂起：显式超时，避免单次请求阻塞数分钟无反馈
            timeout=120,
        )

    @classmethod
    def get_embedding(cls):
        return OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            base_url=settings.EMBEDDING_API_BASE,
            api_key=settings.EMBEDDING_API_KEY,
            timeout=60,
        )
