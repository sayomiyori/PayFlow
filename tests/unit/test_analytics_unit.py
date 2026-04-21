from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api.routers.analytics import _parse_period


def test_parse_period_valid_7d_window() -> None:
    before = datetime.now(UTC)
    since = _parse_period("7d")
    after = datetime.now(UTC)
    delta_low = before - since
    delta_high = after - since
    assert timedelta(days=6, hours=23) < delta_low <= timedelta(days=7, minutes=1)
    assert timedelta(days=6, hours=23) < delta_high <= timedelta(days=7, minutes=1)


def test_parse_period_invalid_suffix() -> None:
    with pytest.raises(HTTPException) as exc:
        _parse_period("7h")
    assert exc.value.status_code == 400


def test_parse_period_non_int_prefix() -> None:
    with pytest.raises(HTTPException) as exc:
        _parse_period("xd")
    assert exc.value.status_code == 400


def test_parse_period_non_positive() -> None:
    with pytest.raises(HTTPException) as exc:
        _parse_period("0d")
    assert exc.value.status_code == 400
