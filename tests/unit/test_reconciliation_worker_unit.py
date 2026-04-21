from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.tenant_models import PaymentStatus


@pytest.mark.asyncio
async def test_fetch_status_from_mock_200(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.workers import reconciliation_worker as rw

    response = MagicMock()
    response.status_code = 200
    response.json = MagicMock(return_value={"status": "completed"})

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        get = AsyncMock(return_value=response)

    monkeypatch.setattr(rw, "AsyncClient", _FakeClient)

    status = await rw._fetch_status_from_mock("mid", "pid")
    assert status == PaymentStatus.COMPLETED


@pytest.mark.asyncio
async def test_fetch_status_from_mock_non_200_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers import reconciliation_worker as rw

    response = MagicMock()
    response.status_code = 503

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        get = AsyncMock(return_value=response)

    monkeypatch.setattr(rw, "AsyncClient", _FakeClient)

    status = await rw._fetch_status_from_mock("mid", "pid")
    assert status == PaymentStatus.PROCESSING
