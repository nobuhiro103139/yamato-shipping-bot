from fastapi import APIRouter, HTTPException
from app.services.yamato_automation import process_shipment, save_auth_state
from app.models.order import ShopifyOrder, ShippingResult

router = APIRouter(prefix="/api/shipping", tags=["shipping"])


@router.post("/process", response_model=ShippingResult)
async def process_order_shipment(order: ShopifyOrder):
    try:
        result = await process_shipment(order)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/init-auth")
async def initialize_auth():
    result = await save_auth_state()
    return result
