from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from clickhouse_driver import Client

from app.core.config import get_settings

settings = get_settings()


class ClickHouseEventStore:
    # [ЧТО] Инкапсулирует чтение/запись payment events в ClickHouse.
    # [ПОЧЕМУ] Отдельный store изолирует SQL и упрощает тестирование consumer/API.
    # [ОСТОРОЖНО] clickhouse-driver синхронный, поэтому вызовы оборачиваем в asyncio.to_thread.
    def __init__(self, client: Client | None = None) -> None:
        self._client = client or Client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            database=settings.clickhouse_db,
        )

    async def insert_events(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        prepared = [
            (
                row["merchant_id"],
                row["payment_id"],
                row["event_type"],
                row["amount"],
                row["currency"],
                row["status"],
                row["created_at"],
            )
            for row in rows
        ]
        await asyncio.to_thread(
            self._client.execute,
            (
                "INSERT INTO payment_events "
                "(merchant_id, payment_id, event_type, amount, currency, status, created_at) "
                "VALUES"
            ),
            prepared,
        )

    async def summary(self, merchant_id: str, since: datetime) -> dict[str, Any]:
        result = await asyncio.to_thread(
            self._client.execute,
            (
                "SELECT "
                "sum(amount) AS total_volume, "
                "count() AS total_count, "
                "avg(amount) AS avg_amount, "
                "sum(if(status IN ('completed','succeeded'), 1, 0)) AS success_count "
                "FROM payment_events "
                "WHERE merchant_id = %(merchant_id)s AND created_at >= %(since)s"
            ),
            {"merchant_id": merchant_id, "since": since},
        )
        total_volume, total_count, avg_amount, success_count = result[0]
        if total_count == 0:
            return {
                "total_volume": Decimal("0"),
                "total_count": 0,
                "success_rate": 0.0,
                "avg_amount": Decimal("0"),
            }
        return {
            "total_volume": total_volume,
            "total_count": int(total_count),
            "success_rate": float(success_count) / float(total_count),
            "avg_amount": avg_amount or Decimal("0"),
        }

    async def timeline(
        self,
        merchant_id: str,
        since: datetime,
        granularity: str,
    ) -> list[dict[str, Any]]:
        bucket_expr = (
            "toStartOfHour(created_at)"
            if granularity == "hour"
            else "toDate(created_at)"
        )
        rows = await asyncio.to_thread(
            self._client.execute,
            (
                "SELECT "
                f"{bucket_expr} AS bucket, "
                "sum(amount) AS total_volume, "
                "count() AS total_count "
                "FROM payment_events "
                "WHERE merchant_id = %(merchant_id)s AND created_at >= %(since)s "
                "GROUP BY bucket "
                "ORDER BY bucket ASC"
            ),
            {"merchant_id": merchant_id, "since": since},
        )
        return [
            {
                "bucket": bucket
                if isinstance(bucket, datetime)
                else datetime.combine(bucket, datetime.min.time(), tzinfo=UTC),
                "total_volume": total_volume,
                "total_count": int(total_count),
            }
            for bucket, total_volume, total_count in rows
        ]

    async def by_currency(
        self, merchant_id: str, since: datetime
    ) -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(
            self._client.execute,
            (
                "SELECT currency, sum(amount) AS total_volume, count() AS total_count "
                "FROM payment_events "
                "WHERE merchant_id = %(merchant_id)s AND created_at >= %(since)s "
                "GROUP BY currency "
                "ORDER BY currency ASC"
            ),
            {"merchant_id": merchant_id, "since": since},
        )
        return [
            {
                "currency": currency,
                "total_volume": total_volume,
                "total_count": int(total_count),
            }
            for currency, total_volume, total_count in rows
        ]
