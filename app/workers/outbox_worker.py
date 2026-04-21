import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from aiokafka import AIOKafkaProducer
from prometheus_client import Counter, Gauge
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.workers.celery_app import celery_app

settings = get_settings()
EVENTS_TOPIC = "payments.events"
BATCH_SIZE = 100

outbox_lag_gauge = Gauge("outbox_lag_gauge", "Total pending outbox records")
events_published_counter = Counter(
    "events_published_counter", "Total published outbox events"
)


async def _list_tenant_schemas(db: AsyncSession) -> list[str]:
    rs = await db.execute(
        text(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name LIKE 'merchant_%'"
        )
    )
    return [row[0] for row in rs.fetchall()]


async def _pending_count_for_schema(db: AsyncSession, schema_name: str) -> int:
    await db.execute(text(f'SET search_path TO "{schema_name}", public'))
    try:
        rs = await db.execute(
            text("SELECT COUNT(*) FROM outbox WHERE processed = FALSE")
        )
        return int(rs.scalar_one())
    except ProgrammingError:
        return 0


async def _process_schema_batch(
    db: AsyncSession,
    producer: AIOKafkaProducer,
    schema_name: str,
) -> int:
    await db.execute(text(f'SET search_path TO "{schema_name}", public'))
    try:
        rows = await db.execute(
            text(
                "SELECT id, event_type, aggregate_id, payload "
                "FROM outbox "
                "WHERE processed = FALSE "
                "ORDER BY created_at "
                "FOR UPDATE SKIP LOCKED "
                "LIMIT :batch_size"
            ),
            {"batch_size": BATCH_SIZE},
        )
    except ProgrammingError:
        return 0
    records = rows.fetchall()
    if not records:
        return 0

    for row in records:
        payload: dict[str, Any] = row.payload
        event_payload = {
            "tenant_schema": schema_name,
            "event_type": row.event_type,
            "aggregate_id": str(row.aggregate_id),
            "payload": payload,
            "published_at": datetime.now(UTC).isoformat(),
        }
        await producer.send_and_wait(
            EVENTS_TOPIC,
            json.dumps(event_payload).encode("utf-8"),
        )
        await db.execute(
            text(
                "UPDATE outbox "
                "SET processed = TRUE, processed_at = NOW() "
                "WHERE id = :event_id"
            ),
            {"event_id": row.id},
        )
    return len(records)


async def process_outbox_batch() -> int:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    total_published = 0

    try:
        async with session_factory() as db:
            schemas = await _list_tenant_schemas(db)

        await producer.start()
        total_lag = 0
        for schema in schemas:
            async with session_factory() as db:
                lag = await _pending_count_for_schema(db, schema)
                total_lag += lag

            async with session_factory() as db, db.begin():
                published = await _process_schema_batch(db, producer, schema)
                total_published += published
                if published:
                    events_published_counter.inc(published)
        outbox_lag_gauge.set(total_lag)
    finally:
        await producer.stop()
        await engine.dispose()

    return total_published


@celery_app.task(name="app.workers.outbox_worker.publish_pending_outbox_events")
def publish_pending_outbox_events() -> int:
    return asyncio.run(process_outbox_batch())
