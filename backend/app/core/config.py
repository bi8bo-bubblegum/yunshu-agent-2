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

    # ---- 钉钉企业内部应用对接（未配置 DINGTALK_CLIENT_ID 时钉钉功能自动禁用）----
    DINGTALK_CLIENT_ID: str = ""             # Client ID（原 AppKey）
    DINGTALK_CLIENT_SECRET: str = ""         # Client Secret（原 AppSecret）
    DINGTALK_CORP_ID: str = ""               # 企业组织 ID
    DINGTALK_AGENT_ID: str = ""              # H5 微应用标识
    DINGTALK_STREAM_ENABLED: bool = False    # 是否启动 Stream 事件订阅常驻任务
    DINGTALK_SYNC_INTERVAL_MINUTES: int = 60 # 组织同步定时兜底间隔
    # 审批类目 → 钉钉审批模板 processCode 映射（JSON 对象，如 {"tool_call":"PROC-XXX"}）
    DINGTALK_OA_PROCESS_CODES: dict[str, str] = {}
    # 是否将钉钉部门主管自动映射为本地 dept_owner（默认关，角色体系本地维护）
    DINGTALK_AUTO_DEPT_OWNER_ROLE: bool = False

    model_config = {"env_file": ".env"}

    @property
    def dingtalk_enabled(self) -> bool:
        """钉钉功能是否启用：凭证已配置。"""
        return bool(self.DINGTALK_CLIENT_ID and self.DINGTALK_CLIENT_SECRET)

settings = Settings()