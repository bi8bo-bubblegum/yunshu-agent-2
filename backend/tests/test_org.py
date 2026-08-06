# backend/tests/test_org.py
import pytest
from sqlalchemy import select
from app.models.org import Department, Role, User

@pytest.mark.asyncio
async def test_create_user_with_department(db_session):
    dept = Department(name="市场部")
    db_session.add(dept)
    await db_session.flush()
    role = Role(code="member", name="成员")
    db_session.add(role)
    await db_session.flush()
    user = User(username="alice", password_hash="x", department_id=dept.id, role_code=role.code, display_name="爱丽丝")
    db_session.add(user)
    await db_session.flush()
    # 不使用 relationship，通过 department_id 手动查关联
    result = await db_session.get(User, user.id)
    assert result.department_id == dept.id
    dept_result = await db_session.get(Department, result.department_id)
    assert dept_result.name == "市场部"
    role_result = await db_session.scalar(select(Role).where(Role.code == result.role_code))
    assert role_result.code == "member"
