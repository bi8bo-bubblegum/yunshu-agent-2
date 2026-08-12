# backend/app/schemas/org.py
from pydantic import BaseModel

class DepartmentCreate(BaseModel):
    name: str

class DepartmentOut(BaseModel):
    id: str
    name: str
    owner_id: str | None = None
    model_config = {"from_attributes": True}

class UserUpdate(BaseModel):
    """组织管理分配角色/部门：缺省字段不修改，显式 null 清空（仅 admin 可调用）。
    role_code: member/dept_owner/admin；department_id: 部门 id 或 null（无部门）。"""
    role_code: str | None = None
    department_id: str | None = None