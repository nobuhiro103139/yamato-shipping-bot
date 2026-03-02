from pydantic import BaseModel
from enum import Enum


class PackageSize(str, Enum):
    COMPACT = "compact"
    S = "S"
    M = "M"
    L = "L"
    LL = "LL"


class DeliveryTimeSlot(str, Enum):
    NONE = "0"
    MORNING = "1"
    PM_14_16 = "3"
    PM_16_18 = "4"
    PM_18_20 = "5"
    PM_19_21 = "7"


class ShippingAddress(BaseModel):
    last_name: str
    first_name: str = ""
    postal_code: str
    province: str = ""
    city: str = ""
    address1: str = ""
    address2: str = ""
    phone: str = ""
    chome: str = ""
    banchi: str = ""
    go: str = ""
    building: str = ""


class OrderItem(BaseModel):
    title: str
    quantity: int


class RentalOrder(BaseModel):
    """A rental order ready for Yamato shipping automation.

    Populated from Supabase ``rentals`` + ``customers`` tables.
    """

    order_id: str
    order_number: str
    shipping_address: ShippingAddress
    items: list[OrderItem]
    package_size: PackageSize = PackageSize.M
    delivery_date: str = ""  # YYYYMMDD
    delivery_time: DeliveryTimeSlot = DeliveryTimeSlot.NONE
    customer_email: str = ""


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
