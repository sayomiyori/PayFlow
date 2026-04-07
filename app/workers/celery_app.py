from celery import Celery
from celery.schedules import crontab, schedule

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "payflow",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.beat_schedule = {
    "publish-outbox-events": {
        "task": "app.workers.outbox_worker.publish_pending_outbox_events",
        "schedule": schedule(1.0),
    },
    "run-payment-reconciliation": {
        "task": "app.workers.reconciliation_worker.run_reconciliation_task",
        "schedule": crontab(minute="*/5"),
    },
}
