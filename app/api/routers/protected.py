from fastapi import APIRouter, Depends

from app.api.dependencies.auth import check_rate_limit, get_current_merchant
from app.infrastructure.db.models import Merchant

router = APIRouter(prefix="/protected", tags=["protected"])


@router.get("/me")
async def get_me(
    merchant: Merchant = Depends(get_current_merchant),
):
    return {
        "merchant_id": merchant.id,
        "email": merchant.email,
        "plan": merchant.plan.value,
        "schema_name": merchant.schema_name,
    }


@router.get("/limited-ping")
async def limited_ping(
    merchant: Merchant = Depends(check_rate_limit),
):
    return {
        "ok": True,
        "merchant_id": merchant.id,
    }
