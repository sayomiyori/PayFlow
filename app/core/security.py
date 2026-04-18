import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """
    Hashing password using bcrypt
    Always returning diff hash (bcrypt adds salt automatically)
    This protects by rainbow table attack

    """
    salt = bcrypt.gensalt()
    pwd_bytes = password.encode("utf-8")
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Checking password without his "decryptions" - bcrypt one-sided
    We hashing plain_password and compare with hashed_password.
    """
    pwd_bytes = plain_password.encode("utf-8")
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(pwd_bytes, hashed_bytes)


def generate_api_key() -> str:
    """
    Generating cryptographically secure API key
    secrets.token_hex(32) = 64 symbols hex, 256 bits entropy

    Used for machine-to-machine authentication between services.
    """
    return secrets.token_hex(32)


def create_access_token(data: dict[str, Any]) -> str:
    """
    Creating JWBT access token

    JWT structure: header.payload.signature
    - header: signature algorithms
    - payload: ours data (sub = merchant_id, exp = expiration)
    - signature: HMAC - SHA256(header + payload, SECRET_KEY)

    Only we can knowing SECRET_KEY only we can creating valid signature
    Client can reading payload (he not encrypted, only signed!)
    but cant modify it without breaking signature
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    return str(jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM))


def create_refresh_token(data: dict[str, Any]) -> str:
    """
    Refresh Token living longer access token (30 days vs 15 minutes)
    Using only to taking new access token (when access token expired)
    Need to store it safely (httpOnly or secure storage)
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    to_encode.update({"exp": expire, "type": "refresh"})
    return str(jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM))


def decode_token(token: str) -> dict[str, Any]:
    """
    Decoding and verifying JWT token
    jose automatically checking signature and expiration time
    By invalid token we raise JWTError
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return cast(dict[str, Any], payload)
    except JWTError as e:
        raise ValueError(f"Invalid token: {e}") from e
