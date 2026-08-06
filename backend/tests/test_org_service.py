# backend/tests/test_org_service.py
import pytest
from app.services.org_service import OrgService

@pytest.mark.asyncio
async def test_create_and_list_department(db_session):
    svc = OrgService(db_session)
    dept = await svc.create_department("市场部")
    assert dept.name == "市场部"
    depts = await svc.list_departments()
    assert any(d.id == dept.id for d in depts)
