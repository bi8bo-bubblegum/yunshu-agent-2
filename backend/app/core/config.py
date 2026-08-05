from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET: str
    JWT_EXPIRE_MINUTES: int = 10080
    DEFAULT_MODEL: str = "best-1"
    EMBEDDING_MODEL: str = "text-embedding-v3-small"
    EMBEDDING_API_BASE: str
    EMBEDDING_API_KEY: str
    MODEL_API_BASE: str
    MODEL_API_KEY: str = ""
    FRONTEND_ORIGINS: str = "http://localhost:5173"

    model_config = {"env_file": ".env"}

settings = Settings()