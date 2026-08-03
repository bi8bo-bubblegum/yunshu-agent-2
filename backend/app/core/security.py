from idlelib import __main__

import jwt

from datetime import datetime, timedelta, timezone
from bcrypt import hashpw, gensalt, checkpw
from app.core.config import settings

def hash_password(plain_password: str) -> str:
    return hashpw(plain_password.encode("utf-8"), gensalt()).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

def create_access_token(user_id: str, username: str) -> str:
    payload = {
        "sub": user_id,
        "username": username,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

def decode_token(token: str) -> str:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])