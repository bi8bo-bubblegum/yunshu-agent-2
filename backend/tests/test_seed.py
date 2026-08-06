# backend/tests/test_seed.py
import pytest
from sqlalchemy import select
from app.models.org import Role
from app.services.seed import seed_roles

@pytest.mark.asyncio
async def test_seed_creates_defaults(db_session):
    await seed_roles(db_session)
    roles = (await db_session.scalars(select(Role))).all()
    assert {r.code for r in roles} >= {"member", "dept_owner", "admin"}
