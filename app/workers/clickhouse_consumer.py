from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from aiokafka import AIOKafkaConsumer
from prometheus_client import Gauge, start_http_server

from app.core.config import get_settings
from app.infrastructure.clickhouse.client import ClickHouseEventStore

settings = get_settings()
TOPIC = "payments.events"
GROUP_ID = "clickhouse-sink"
BATCH_SIZE = 500
FLUSH_INTERVAL_SECONDS = 2
METRICS_PORT = int(os.getenv("CLICKHOUSE_CONSUMER_METRICS_PORT", "9108"))

ch_insert_batch_size = Gauge(
    "ch_insert_batch_size",
    "Inserted ClickHouse batch size",
)
ch_consumer_lag = Gauge(
    "ch_consumer_lag",
    "Kafka consumer lag for ClickHouse sink",
)


def _safe_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _extract_row(raw_payload: bytes) -> dict[str, Any]:
    # [ЧТО] Преобразует событие Kafka в строку для ClickHouse.
    # [ПОЧЕМУ] Единая нормализация защищает sink от вариативности payload между event_type.
    # [ОСТОРОЖНО] Пустые amount/status приводятся к безопасным значениям, чтобы не ронять batch.
    event = json.loads(raw_payload.decode("utf-8"))
    payload = event.get("payload", {})
    created_at = event.get("published_at") or datetime.now(UTC).isoformat()
    return {
        "merchant_id": str(payload.get("merchant_id", "unknown")),
        "payment_id": str(payload.get("payment_id", event.get("aggregate_id", ""))),
        "event_type": str(event.get("event_type", "unknown")),
        "amount": _safe_decimal(payload.get("amount", "0")),
        "currency": str(payload.get("currency", "UNK")),
        "status": str(payload.get("status", "unknown"))
        .replace("PaymentStatus.", "")
        .lower(),
        "created_at": datetime.fromisoformat(created_at.replace("Z", "+00:00")),
    }


class ClickHouseConsumerService:
    # [ЧТО] Читает Kafka events и батчево пишет в ClickHouse с manual commit offsets.
    # [ПОЧЕМУ] Manual commit дает backpressure: если insert неуспешен, offset не подтверждается.
    # [ОСТОРОЖНО] При очень больших лагах стоит добавить DLQ/retention-алерты, иначе топик разрастется.
    def __init__(
        self,
        event_store: ClickHouseEventStore | None = None,
        consumer: AIOKafkaConsumer | None = None,
    ) -> None:
        self._event_store = event_store or ClickHouseEventStore()
        self._consumer = consumer or AIOKafkaConsumer(
            TOPIC,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=GROUP_ID,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        self._running = False

    async def start(self) -> None:
        self._running = True
        await self._consumer.start()

    async def stop(self) -> None:
        self._running = False
        await self._consumer.stop()

    async def process_batch(self, records: list[Any]) -> int:
        if not records:
            return 0
        rows = [_extract_row(msg.value) for msg in records]
        await self._event_store.insert_events(rows)
        ch_insert_batch_size.set(len(rows))
        await self._consumer.commit()
        return len(rows)

    async def _update_lag_metric(self) -> int:
        lag_total = 0
        for partition in self._consumer.assignment():
            highwater = self._consumer.highwater(partition) or 0
            position = await self._consumer.position(partition)
            lag_total += max(highwater - position, 0)
        ch_consumer_lag.set(lag_total)
        return lag_total

    async def consume_once(self) -> int:
        records_map = await self._consumer.getmany(
            timeout_ms=FLUSH_INTERVAL_SECONDS * 1000,
            max_records=BATCH_SIZE,
        )
        records = [record for batch in records_map.values() for record in batch]
        if records:
            inserted = await self.process_batch(records)
            await self._update_lag_metric()
            return inserted

        await self._update_lag_metric()
        return 0

    async def run_forever(self) -> None:
        await self.start()
        try:
            while self._running:
                await self.consume_once()
        finally:
            await self.stop()


async def run_clickhouse_consumer() -> None:
    start_http_server(METRICS_PORT)
    service = ClickHouseConsumerService()
    await service.run_forever()


if __name__ == "__main__":
    asyncio.run(run_clickhouse_consumer())
