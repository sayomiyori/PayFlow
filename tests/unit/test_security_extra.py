import pytest
from jose import jwt

from app.core.config import get_settings
from app.core.security import (
    ALGORITHM,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_api_key,
    hash_password,
    verify_password,
)

settings = get_settings()


def test_hash_and_verify_roundtrip() -> None:
    h = hash_password("secret123")
    assert verify_password("secret123", h) is True
    assert verify_password("wrong", h) is False


def test_generate_api_key_length() -> None:
    key = generate_api_key()
    assert len(key) == 64


def test_access_refresh_decode_roundtrip() -> None:
    data = {"sub": "merchant-uuid"}
    access = create_access_token(data)
    refresh = create_refresh_token(data)
    assert decode_token(access)["sub"] == "merchant-uuid"
    assert decode_token(refresh)["type"] == "refresh"


def test_decode_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Invalid token"):
        decode_token("not.a.jwt")


def test_token_payload_contains_exp() -> None:
    token = create_access_token({"sub": "x"})
    payload = jwt.get_unverified_claims(token)
    assert "exp" in payload
    assert payload["type"] == "access"
