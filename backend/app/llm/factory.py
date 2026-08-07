from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import settings

MODEL_MAP = {
    "default": "best-2-openai",
    "marketing": "best-2-openai",
    "sales_analysis": "best-2-openai",
    "scheduling": "best-2-openai"
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
