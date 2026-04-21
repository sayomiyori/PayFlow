from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.db.tenant import get_tenant_session


@pytest.mark.asyncio
async def test_get_tenant_session_sets_path_and_returns_same_session() -> None:
    db = MagicMock()
    db.execute = AsyncMock()
    out = await get_tenant_session(db, "550e8400-e29b-41d4-a716-446655440000")  # type: ignore[arg-type]
    assert out is db
    assert db.execute.await_count == 1
