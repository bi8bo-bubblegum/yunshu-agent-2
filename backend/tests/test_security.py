# backend/tests/test_security.py
import pytest
from app.core.security import hash_password, verify_password, create_access_token, decode_token

def test_hash_and_verify():
    h = hash_password("pass123")
    assert h != "pass123"
    assert verify_password("pass123", h)
    assert not verify_password("wrong", h)

def test_token_roundtrip():
    token = create_access_token("u1", "alice")
    payload = decode_token(token)
    assert payload["sub"] == "u1" and payload["username"] == "alice"
