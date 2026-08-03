# backend/app/schemas/org.py
from pydantic import BaseModel

class DepartmentCreate(BaseModel):
    name: str

class DepartmentOut(BaseModel):
    id: str
    name: str
    owner_id: str | None = None
    model_config = {"from_attributes": True}