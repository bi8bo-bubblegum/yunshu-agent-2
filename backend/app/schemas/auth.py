# backend/app/schemas/auth.py
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
    model_config = {"from_attributes": True}