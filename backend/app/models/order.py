from pydantic import BaseModel
from enum import Enum


class PackageSize(str, Enum):
    """Yamato package size categories."""

    S = "S"
    M = "M"
    L = "L"
    LL = "LL"


class ShippingAddress(BaseModel):
    """Recipient shipping address extracted from a Shopify order."""

    last_name: str
    first_name: str = ""
    postal_code: str
    province: str
    city: str
    address1: str
    address2: str = ""
    phone: str = ""


class OrderItem(BaseModel):
    """A single line item in a Shopify order."""

    title: str
    quantity: int


class ShopifyOrder(BaseModel):
    """An unfulfilled Shopify order with shipping details."""

    order_id: str
    order_number: str
    shipping_address: ShippingAddress
    items: list[OrderItem]
    package_size: PackageSize = PackageSize.M


class ShippingStatus(str, Enum):
    """Possible states of a shipment processing attempt."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ShippingResult(BaseModel):
    """Result of processing a single order through Yamato automation."""

    order_id: str
    order_number: str
    status: ShippingStatus
    qr_code_path: str = ""
    error_message: str = ""
