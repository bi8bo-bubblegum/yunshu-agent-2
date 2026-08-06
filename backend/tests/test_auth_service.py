# backend/tests/test_auth_service.py
import pytest
from fastapi import HTTPException
from app.services.auth_service import AuthService

@pytest.mark.asyncio
async def test_register_and_login_service(db_session):
    svc = AuthService(db_session)
    user = await svc.register("alice", "pass123", "Alice")
    assert user.username == "alice"
    token = await svc.login("alice", "pass123")
    assert token

@pytest.mark.asyncio
async def test_login_wrong_password(db_session):
    svc = AuthService(db_session)
    await svc.register("bob", "pass123", "Bob")
    with pytest.raises(HTTPException) as e:
        await svc.login("bob", "wrong")
    assert e.value.status_code == 400
