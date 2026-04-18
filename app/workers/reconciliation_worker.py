import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

from httpx import ASGITransport, AsyncClient
from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.types import ASGIApp

from app.core.config import get_settings
from app.infrastructure.db.models import Merchant
from app.infrastructure.db.tenant import get_tenant_session
from app.infrastructure.db.tenant_models import Outbox, Payment, PaymentStatus
from app.main import app
from app.workers.celery_app import celery_app

settings = get_settings()

reconciliation_corrected_counter = Counter(
    "reconciliation_corrected",
    "Payments corrected by reconciliation worker",
)


async def _fetch_status_from_mock(
    merchant_id: str,
    provider_payment_id: str,
) -> PaymentStatus:
    # [ЧТО] Забирает статус платежа через mock endpoint ЮKassa с помощью httpx.AsyncClient.
    # [ПОЧЕМУ] Так мы используем тот же HTTP-контракт, что и реальный провайдер, а не прямой вызов БД.
    # [ОСТОРОЖНО] При росте нагрузки лучше переключить на отдельный HTTP-клиент к внешнему URL, не в ASGITransport.
    async with AsyncClient(
        transport=ASGITransport(app=cast(ASGIApp, app)),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/mock/yukassa/status/{provider_payment_id}",
            params={"merchant_id": merchant_id},
        )
        if response.status_code != 200:
            return PaymentStatus.PROCESSING
        payload = response.json()
        return PaymentStatus(payload["status"])


async def run_reconciliation() -> int:
    # [ЧТО] Ищет застрявшие processing-платежи и корректирует их статус по данным ЮKassa.
    # [ПОЧЕМУ] Это закрывает дыры доставки webhook-ов и не оставляет платежи в промежуточном состоянии навсегда.
    # [ОСТОРОЖНО] Нужна идемпотентность: один и тот же платеж может попасть в несколько циклов worker-а.
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    corrected = 0
    threshold = datetime.now(UTC) - timedelta(
        seconds=settings.reconciliation_stuck_seconds
    )

    try:
        async with session_factory() as db:
            merchants = (await db.execute(select(Merchant))).scalars().all()

        for merchant in merchants:
            async with session_factory() as db:
                tenant_db = await get_tenant_session(db, merchant.id)
                stuck = (
                    (
                        await tenant_db.execute(
                            select(Payment).where(
                                (Payment.status == PaymentStatus.PROCESSING)
                                & (Payment.updated_at < threshold)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

                for payment in stuck:
                    if not payment.provider_payment_id:
                        continue
                    provider_status = await _fetch_status_from_mock(
                        merchant.id,
                        payment.provider_payment_id,
                    )
                    if provider_status != payment.status:
                        payment.status = provider_status
                        payment.updated_at = datetime.now(UTC)
                        tenant_db.add(
                            Outbox(
                                event_type="payment.status_changed",
                                aggregate_id=payment.id,
                                payload={
                                    "payment_id": str(payment.id),
                                    "provider_payment_id": payment.provider_payment_id,
                                    "status": payment.status.value,
                                    "source": "reconciliation",
                                },
                                processed=False,
                            )
                        )
                        corrected += 1

                await tenant_db.commit()
        reconciliation_corrected_counter.inc(corrected)
        return corrected
    finally:
        await engine.dispose()


@celery_app.task(name="app.workers.reconciliation_worker.run_reconciliation_task")
def run_reconciliation_task() -> int:
    return asyncio.run(run_reconciliation())
