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
    package_size: PackageSize = PackageSize.COMPACT
    delivery_date: str = ""  # YYYYMMDD
    delivery_time: DeliveryTimeSlot = DeliveryTimeSlot.NONE
    customer_email: str = ""


class ShippingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationField(BaseModel):
    """Single field comparison result."""

    field: str
    expected: str
    actual: str
    match: bool


class VerificationReport(BaseModel):
    """Post-save verification report comparing expected vs actual values."""

    order_number: str
    timestamp: str
    fields: list[VerificationField] = []
    mismatches: list[VerificationField] = []
    page_text_snippet: str = ""
    verified: bool = False

    def add(self, field: str, expected: str, actual: str) -> None:
        expected_s = str(expected).strip()
        actual_s = str(actual).strip()
        entry = VerificationField(
            field=field,
            expected=expected_s,
            actual=actual_s,
            match=expected_s == actual_s,
        )
        self.fields.append(entry)
        if not entry.match:
            self.mismatches.append(entry)

    @property
    def all_match(self) -> bool:
        return len(self.mismatches) == 0 and len(self.fields) > 0


class ShippingResult(BaseModel):
    order_id: str
    order_number: str
    status: ShippingStatus
    qr_code_path: str = ""
    error_message: str = ""
    verification: VerificationReport | None = None
