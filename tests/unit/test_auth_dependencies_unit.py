from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.dependencies import auth as auth_dep
from app.infrastructure.db.models import Merchant, MerchantPlan


@pytest.mark.asyncio
async def test_get_current_merchant_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_dep, "decode_token", lambda _t: {"sub": "mid-1"})

    merchant = MagicMock(spec=Merchant)
    merchant.id = "mid-1"
    merchant.is_active = True

    result = MagicMock()
    result.scalar_one_or_none.return_value = merchant
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
    out = await auth_dep.get_current_merchant(creds, db)  # type: ignore[arg-type]
    assert out is merchant


@pytest.mark.asyncio
async def test_get_current_merchant_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_dep,
        "decode_token",
        MagicMock(side_effect=ValueError("bad")),
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")
    db = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await auth_dep.get_current_merchant(credentials=creds, db=db)  # type: ignore[arg-type]
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_merchant_inactive_or_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_dep, "decode_token", lambda _t: {"sub": "mid-1"})

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="tok")
    with pytest.raises(HTTPException) as exc:
        await auth_dep.get_current_merchant(creds, db)  # type: ignore[arg-type]
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_merchant_missing_sub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_dep, "decode_token", lambda _t: {})
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="x")
    db = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await auth_dep.get_current_merchant(credentials=creds, db=db)  # type: ignore[arg-type]
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_check_rate_limit_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_dep.rate_limiter,
        "is_allowed",
        AsyncMock(return_value=(False, 0)),
    )
    merchant = MagicMock(spec=Merchant)
    merchant.id = "m1"
    merchant.plan = MerchantPlan.FREE

    with pytest.raises(HTTPException) as exc:
        await auth_dep.check_rate_limit(merchant=merchant)  # type: ignore[arg-type]
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_check_rate_limit_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_dep.rate_limiter,
        "is_allowed",
        AsyncMock(return_value=(True, 10)),
    )
    merchant = MagicMock(spec=Merchant)
    merchant.id = "m1"
    merchant.plan = MerchantPlan.PRO

    out = await auth_dep.check_rate_limit(merchant=merchant)  # type: ignore[arg-type]
    assert out is merchant


@pytest.mark.asyncio
async def test_inject_tenant_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_session = MagicMock()
    monkeypatch.setattr(
        auth_dep,
        "get_tenant_session",
        AsyncMock(return_value=tenant_session),
    )
    merchant = MagicMock(spec=Merchant)
    merchant.id = "mid"
    db = MagicMock()

    sess = await auth_dep.inject_tenant(merchant=merchant, db=db)  # type: ignore[arg-type]
    assert sess is tenant_session
