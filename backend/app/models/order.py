from pydantic import BaseModel
from enum import Enum


class PackageSize(str, Enum):
    S = "S"
    M = "M"
    L = "L"
    LL = "LL"


class ShippingAddress(BaseModel):
    name: str
    postal_code: str
    province: str
    city: str
    address1: str
    address2: str = ""
    phone: str = ""


class OrderItem(BaseModel):
    title: str
    quantity: int


class ShopifyOrder(BaseModel):
    order_id: str
    order_number: str
    shipping_address: ShippingAddress
    items: list[OrderItem]
    package_size: PackageSize = PackageSize.M


class ShippingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ShippingResult(BaseModel):
    order_id: str
    order_number: str
    status: ShippingStatus
    qr_code_path: str = ""
    error_message: str = ""
