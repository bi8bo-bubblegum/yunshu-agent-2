# backend/app/schemas/auth.py
from datetime import datetime

from pydantic import BaseModel

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    department_id: str | None = None
    role_code: str | None = None
    # 钉钉同步字段（组织管理页展示）
    dingtalk_userid: str | None = None
    source: str | None = None
    status: str | None = None
    title: str | None = None
    mobile: str | None = None
    synced_at: datetime | None = None
    model_config = {"from_attributes": True}