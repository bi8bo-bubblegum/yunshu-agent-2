from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import settings

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
            temperature=0.3
        )

    @classmethod
    def get_embedding(cls):
        return OpenAIEmbeddings(
            model=settings.EMBEDDING_MODEL,
            base_url=settings.MODEL_API_BASE,
            api_key=settings.MODEL_API_KEY,
        )