from fastapi import APIRouter, HTTPException
from app.services.yamato_agent import process_shipment
from app.models.order import Shipment, ShippingResult

router = APIRouter(prefix="/api/shipping", tags=["shipping"])


@router.post("/process", response_model=ShippingResult)
async def process_shipment_endpoint(shipment: Shipment) -> ShippingResult:
    """Process a single shipment through Browser Use agent."""
    try:
        result = await process_shipment(shipment)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
