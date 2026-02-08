from fastapi import APIRouter, HTTPException
from app.services.shopify_service import fetch_unfulfilled_orders
from app.models.order import ShopifyOrder

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.get("/unfulfilled", response_model=list[ShopifyOrder])
async def get_unfulfilled_orders():
    try:
        orders = await fetch_unfulfilled_orders()
        return orders
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
