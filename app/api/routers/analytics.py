from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.dependencies.auth import get_current_merchant
from app.infrastructure.clickhouse.client import ClickHouseEventStore
from app.infrastructure.db.models import Merchant

router = APIRouter(prefix="/analytics", tags=["analytics"])


class AnalyticsSummaryResponse(BaseModel):
    total_volume: Decimal
    total_count: int
    success_rate: float
    avg_amount: Decimal


class TimelinePoint(BaseModel):
    bucket: datetime
    total_volume: Decimal
    total_count: int


class AnalyticsTimelineResponse(BaseModel):
    items: list[TimelinePoint]


class CurrencyPoint(BaseModel):
    currency: str
    total_volume: Decimal
    total_count: int


class AnalyticsByCurrencyResponse(BaseModel):
    items: list[CurrencyPoint]


def _parse_period(period: str) -> datetime:
    # [ЧТО] Переводит период вида 7d/30d в datetime-нижнюю границу выборки.
    # [ПОЧЕМУ] Компактный формат периода удобен для API и прозрачен для аналитических запросов.
    # [ОСТОРОЖНО] Если период невалидный, отдаём 400, чтобы не запускать неожиданные full scans.
    if not period.endswith("d"):
        raise HTTPException(status_code=400, detail="period must be like 7d or 30d")
    try:
        days = int(period[:-1])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid period format") from exc
    if days <= 0:
        raise HTTPException(status_code=400, detail="period must be positive")
    return datetime.now(UTC) - timedelta(days=days)


@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    period: str = Query(default="7d"),
    merchant: Merchant = Depends(get_current_merchant),
) -> AnalyticsSummaryResponse:
    store = ClickHouseEventStore()
    data = await store.summary(str(merchant.id), _parse_period(period))
    return AnalyticsSummaryResponse(**data)


@router.get("/timeline", response_model=AnalyticsTimelineResponse)
async def get_analytics_timeline(
    period: str = Query(default="30d"),
    granularity: Literal["day", "hour"] = Query(default="day"),
    merchant: Merchant = Depends(get_current_merchant),
) -> AnalyticsTimelineResponse:
    store = ClickHouseEventStore()
    rows = await store.timeline(
        merchant_id=str(merchant.id),
        since=_parse_period(period),
        granularity=granularity,
    )
    return AnalyticsTimelineResponse(items=[TimelinePoint(**row) for row in rows])


@router.get("/by_currency", response_model=AnalyticsByCurrencyResponse)
async def get_analytics_by_currency(
    period: str = Query(default="30d"),
    merchant: Merchant = Depends(get_current_merchant),
) -> AnalyticsByCurrencyResponse:
    store = ClickHouseEventStore()
    rows = await store.by_currency(str(merchant.id), _parse_period(period))
    return AnalyticsByCurrencyResponse(items=[CurrencyPoint(**row) for row in rows])
