import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import ProgrammingError

from app.workers.outbox_worker import (
    _list_tenant_schemas,
    _pending_count_for_schema,
    _process_schema_batch,
)


@pytest.mark.asyncio
async def test_list_tenant_schemas_maps_rows() -> None:
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = [("merchant_a",), ("merchant_b",)]
    db.execute = AsyncMock(return_value=result)

    schemas = await _list_tenant_schemas(db)  # type: ignore[arg-type]
    assert schemas == ["merchant_a", "merchant_b"]


@pytest.mark.asyncio
async def test_pending_count_for_schema_returns_count() -> None:
    db = MagicMock()
    count_rs = MagicMock()
    count_rs.scalar_one.return_value = 7

    db.execute = AsyncMock(side_effect=[MagicMock(), count_rs])

    n = await _pending_count_for_schema(db, "merchant_x")  # type: ignore[arg-type]
    assert n == 7


@pytest.mark.asyncio
async def test_pending_count_for_schema_programming_error_returns_zero() -> None:
    db = MagicMock()
    n_calls = 0

    async def _exec(*_a: object, **_kw: object) -> MagicMock:
        nonlocal n_calls
        n_calls += 1
        if n_calls == 1:
            return MagicMock()
        raise ProgrammingError("stmt", {}, None)

    db.execute = AsyncMock(side_effect=_exec)

    n = await _pending_count_for_schema(db, "merchant_x")  # type: ignore[arg-type]
    assert n == 0


@pytest.mark.asyncio
async def test_process_schema_batch_empty_returns_zero() -> None:
    select_rs = MagicMock()
    select_rs.fetchall.return_value = []
    n_exec = 0

    async def _exec(*_a: object, **_kw: object) -> MagicMock:
        nonlocal n_exec
        n_exec += 1
        if n_exec == 1:
            return MagicMock()
        return select_rs

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_exec)
    producer = MagicMock()

    n = await _process_schema_batch(db, producer, "merchant_t")  # type: ignore[arg-type]
    assert n == 0


@pytest.mark.asyncio
async def test_process_schema_batch_publishes_and_updates() -> None:
    pid = uuid.uuid4()
    row = MagicMock()
    row.id = 42
    row.event_type = "payment.created"
    row.aggregate_id = pid
    row.payload = {"x": 1}

    select_rs = MagicMock()
    select_rs.fetchall.return_value = [row]
    n_exec = 0

    async def _exec(*_a: object, **_kw: object) -> MagicMock:
        nonlocal n_exec
        n_exec += 1
        if n_exec == 1:
            return MagicMock()
        return select_rs

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_exec)
    producer = MagicMock()
    producer.send_and_wait = AsyncMock()

    n = await _process_schema_batch(db, producer, "merchant_t")  # type: ignore[arg-type]
    assert n == 1
    producer.send_and_wait.assert_awaited_once()
    assert db.execute.await_count >= 3


@pytest.mark.asyncio
async def test_process_schema_batch_select_programming_returns_zero() -> None:
    n_exec = 0

    async def _exec(*_a: object, **_kw: object) -> MagicMock:
        nonlocal n_exec
        n_exec += 1
        if n_exec == 1:
            return MagicMock()
        raise ProgrammingError("stmt", {}, None)

    db = MagicMock()
    db.execute = AsyncMock(side_effect=_exec)
    producer = MagicMock()

    n = await _process_schema_batch(db, producer, "merchant_bad")  # type: ignore[arg-type]
    assert n == 0
