"""Supabase PostgREST client for fetching pending rentals and updating shipping status."""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from scripts.config import get_settings
from scripts.models import (
    DeliveryTimeSlot,
    OrderItem,
    PackageSize,
    RentalOrder,
    ShippingAddress,
)

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

SUPABASE_REQUEST_TIMEOUT = 30.0

RENTALS_SELECT = (
    "id,shopify_order_number,product_name,rental_start,rental_end,"
    "shipping_date,delivery_time_slot,"
    "customers(name,postal_code,prefecture,city,address_line,phone,email)"
)

# Map human-readable delivery time slots stored in DB to Yamato form values
DELIVERY_TIME_SLOT_MAP: dict[str, DeliveryTimeSlot] = {
    "8:00~12:00": DeliveryTimeSlot.MORNING,
    "14:00~16:00": DeliveryTimeSlot.PM_14_16,
    "16:00~18:00": DeliveryTimeSlot.PM_16_18,
    "18:00~20:00": DeliveryTimeSlot.PM_18_20,
    "19:00~21:00": DeliveryTimeSlot.PM_19_21,
}


def _parse_delivery_time_slot(slot: str | None) -> DeliveryTimeSlot:
    """Convert human-readable time slot string to Yamato form enum value.

    Handles single slots (e.g. '8:00~12:00') and comma-separated preferences
    (e.g. '8:00~12:00, 14:00~16:00') by taking the first match.
    """
    if not slot or slot == "指定なし":
        return DeliveryTimeSlot.NONE
    first_slot = slot.split(",")[0].strip()
    return DELIVERY_TIME_SLOT_MAP.get(first_slot, DeliveryTimeSlot.NONE)


def _split_name(full_name: str) -> tuple[str, str]:
    """Split a full name into (last_name, first_name).

    Handles both Japanese (e.g. '田中 希明') and Western (e.g. 'ISHII YUNA') formats.
    """
    if not full_name or not full_name.strip():
        return ("", "")
    parts = full_name.strip().split(None, 1)
    if len(parts) == 2:
        return (parts[0], parts[1])
    return (parts[0], "")


def _build_headers(service_role_key: str) -> dict[str, str]:
    """Build HTTP headers for Supabase PostgREST requests."""
    return {
        "apikey": service_role_key,
        "Authorization": f"Bearer {service_role_key}",
        "Content-Type": "application/json",
    }


def _row_to_rental_order(row: dict, default_package_size: str) -> RentalOrder | None:
    """Convert a Supabase row (with joined customer) to a RentalOrder."""
    customer: dict = row.get("customers") or {}
    order_number = row.get("shopify_order_number", "")
    if not customer:
        logger.warning(
            "Rental %s has no linked customer, skipping",
            order_number,
        )
        return None

    last_name, first_name = _split_name(customer.get("name", ""))

    phone = str(customer.get("phone") or "").strip()
    # DB stores phone without leading 0 — restore it for domestic numbers
    if phone and not phone.startswith("0") and not phone.startswith("+"):
        phone = "0" + phone

    address = ShippingAddress(
        last_name=last_name,
        first_name=first_name,
        postal_code=customer.get("postal_code", ""),
        province=customer.get("prefecture", ""),
        city=customer.get("city", ""),
        address1=customer.get("address_line", ""),
        phone=phone,
    )

    rental_start = row.get("rental_start", "")
    delivery_date = ""
    if rental_start:
        try:
            dt = datetime.strptime(rental_start[:10], "%Y-%m-%d")
            delivery_date = dt.strftime("%Y%m%d")
        except (ValueError, TypeError):
            logger.warning("Invalid rental_start format: %s", rental_start)

    delivery_time = _parse_delivery_time_slot(row.get("delivery_time_slot"))
    product_name = row.get("product_name", "レンタル機器")

    rental_id = row.get("id")
    if not rental_id:
        logger.warning("Rental row missing id, skipping: order_number=%s", order_number)
        return None

    try:
        package_size = PackageSize(default_package_size)
    except ValueError:
        logger.warning(
            "Invalid default_package_size '%s'; fallback to '%s'",
            default_package_size,
            PackageSize.M.value,
        )
        package_size = PackageSize.M

    return RentalOrder(
        order_id=rental_id,
        order_number=order_number,
        shipping_address=address,
        items=[OrderItem(title=product_name, quantity=1)],
        package_size=package_size,
        delivery_date=delivery_date,
        delivery_time=delivery_time,
        customer_email=customer.get("email", ""),
    )


async def fetch_pending_rentals(ready_only: bool = False) -> list[RentalOrder]:
    """Fetch pending rentals from Supabase.

    Args:
        ready_only: If True, only return rentals whose shipping_date <= today (JST).
                    Use True for the ``ship`` command, False for ``check``.
    """
    settings = get_settings()
    if not settings.supabase_configured:
        return []

    base_url = settings.supabase_url.rstrip("/")
    url = f"{base_url}/rest/v1/rentals"
    headers = _build_headers(settings.supabase_service_role_key)

    params: list[tuple[str, str]] = [
        ("select", RENTALS_SELECT),
        ("shipping_status", "in.(pending,ready_to_ship)"),
        ("rental_status", "in.(pending,confirmed)"),
        ("order", "shipping_date.asc.nullslast"),
    ]

    if ready_only:
        today = datetime.now(JST).strftime("%Y-%m-%d")
        params.append(("shipping_date", f"lte.{today}"))
    else:
        params.append(("shipping_date", "not.is.null"))

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers=headers,
            params=params,
            timeout=SUPABASE_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        rows: list[dict] = response.json()

    orders: list[RentalOrder] = []
    for row in rows:
        try:
            order = _row_to_rental_order(row, settings.default_package_size)
        except Exception:
            logger.exception(
                "Failed to parse rental row, skipping: id=%s order_number=%s",
                row.get("id"),
                row.get("shopify_order_number"),
            )
            continue
        if order is not None:
            orders.append(order)

    return orders


async def update_rental_shipping_status(
    rental_id: str, status: str, tracking_number: str = ""
) -> None:
    """Update shipping_status (and optionally tracking_number) of a rental in Supabase."""
    settings = get_settings()
    if not settings.supabase_configured:
        logger.error("Supabase not configured, cannot update shipping status")
        return

    base_url = settings.supabase_url.rstrip("/")
    url = f"{base_url}/rest/v1/rentals"
    headers = _build_headers(settings.supabase_service_role_key)
    headers["Prefer"] = "return=representation"

    params = {
        "id": f"eq.{rental_id}",
        "shipping_status": "in.(pending,ready_to_ship)",
    }
    body: dict[str, str] = {"shipping_status": status}
    if tracking_number:
        body["tracking_number"] = tracking_number

    async with httpx.AsyncClient() as client:
        response = await client.patch(
            url,
            headers=headers,
            params=params,
            json=body,
            timeout=SUPABASE_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        updated_rows = response.json()
        if not isinstance(updated_rows, list) or len(updated_rows) != 1:
            row_count = len(updated_rows) if isinstance(updated_rows, list) else "invalid"
            raise RuntimeError(
                f"Expected 1 updated rental for id={rental_id}, got {row_count}"
            )

    masked_id = rental_id[:8] + "..."
    logger.info("Updated rental %s shipping_status -> '%s'", masked_id, status)
