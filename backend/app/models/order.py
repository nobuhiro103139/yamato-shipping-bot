from enum import Enum

from pydantic import BaseModel, computed_field


class PackageSize(str, Enum):
    """Yamato package size categories."""

    COMPACT = "compact"
    S = "S"
    M = "M"
    L = "L"
    LL = "LL"


class DeliveryTimeSlot(str, Enum):
    """Yamato delivery time slot codes matching form select values."""

    NONE = "0"
    MORNING = "1"
    PM_14_16 = "3"
    PM_16_18 = "4"
    PM_18_20 = "5"
    PM_19_21 = "7"


class ShippingAddress(BaseModel):
    """Recipient shipping address extracted from a Shopify order."""

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
    delivery_date: str = ""  # Format: YYYYMMDD (e.g., "20260215")
    delivery_time: DeliveryTimeSlot = DeliveryTimeSlot.NONE
    customer_email: str = ""


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


PACKAGE_SIZE_LABELS: dict[PackageSize, str] = {
    PackageSize.COMPACT: "コンパクト",
    PackageSize.S: "Ｓ",  # noqa: RUF001
    PackageSize.M: "Ｍ",  # noqa: RUF001
    PackageSize.L: "Ｌ",  # noqa: RUF001
    PackageSize.LL: "ＬＬ",  # noqa: RUF001
}


class Shipment(BaseModel):
    """A single shipment to process via Browser Use agent.

    This model represents the data from shipments.json,
    prepared by an upstream agent (e.g. Shopify integration).
    """

    recipient_last_name: str
    recipient_first_name: str = ""
    recipient_postal_code: str
    recipient_phone: str
    recipient_email: str = ""
    recipient_chome: str = ""
    recipient_banchi: str = ""
    recipient_go: str = ""
    recipient_building: str = ""
    product_name: str = "スマートフォン"
    package_size: PackageSize = PackageSize.COMPACT
    shipping_date: str = ""
    delivery_date: str = ""
    delivery_time: str = ""
    order_id: str = ""

    @computed_field
    @property
    def identifier(self) -> str:
        """Unique identifier for logging (order_id or recipient name)."""
        if self.order_id:
            return self.order_id
        return f"{self.recipient_last_name}_{self.recipient_first_name}"

    @computed_field
    @property
    def package_size_label(self) -> str:
        """Japanese label for the package size."""
        return PACKAGE_SIZE_LABELS.get(self.package_size, "コンパクト")
