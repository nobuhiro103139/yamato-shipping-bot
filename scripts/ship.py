import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from scripts.config import get_settings
from scripts.models import (
    DeliveryTimeSlot,
    OrderItem,
    PackageSize,
    RentalOrder,
    ShippingAddress,
)
from scripts.notify import notify_batch_summary, notify_shipment_result
from scripts.shopify_client import fetch_order_by_number
from scripts.supabase_client import fetch_pending_rentals, update_rental_shipping_status
from scripts.yamato_automation import process_shipment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_shipment_batch() -> int:
    settings = get_settings()
    logger.info("Starting shipment batch at %s", datetime.now().isoformat())

    if not settings.supabase_configured:
        logger.error("Supabase credentials not configured")
        return 1

    try:
        orders = await fetch_pending_rentals(ready_only=True)
    except Exception:
        logger.exception("Failed to fetch rentals from Supabase")
        return 1

    if not orders:
        logger.info("No rentals ready to ship today")
        return 0

    logger.info("Found %d rental(s) ready to ship", len(orders))
    completed = 0
    failed = 0

    for order in orders:
        addr = order.shipping_address
        raw_name = addr.last_name or addr.first_name or ""
        masked_name = f"{raw_name[:1]}***" if raw_name else "N/A"
        logger.info(
            "Processing %s — %s",
            order.order_number,
            masked_name,
        )

        try:
            result = await process_shipment(order)
        except Exception as exc:
            logger.exception("Shipment processing crashed for rental %s", order.order_id)
            failed += 1
            try:
                await notify_shipment_result(
                    order.order_number,
                    success=False,
                    error=f"発送処理中に例外: {exc}",
                )
            except Exception:
                logger.exception("Failed to send failure notification for %s", order.order_number)
            continue

        if result.status.value == "completed":
            logger.info("  -> Completed. QR: %s", result.qr_code_path)
            try:
                await update_rental_shipping_status(order.order_id, "shipped")
            except Exception:
                logger.exception("Failed to update shipped status for rental %s", order.order_id)
                failed += 1
                try:
                    await notify_shipment_result(
                        order.order_number,
                        success=False,
                        error="発送は成功しましたがDB更新に失敗しました",
                    )
                except Exception:
                    logger.exception("Failed to send notification for %s", order.order_number)
                continue
            completed += 1
            try:
                await notify_shipment_result(
                    order.order_number, success=True, qr_code_path=result.qr_code_path
                )
            except Exception:
                logger.exception("Failed to send success notification for %s", order.order_number)
        else:
            logger.error("  -> Failed: %s", result.error_message)
            failed += 1
            try:
                await notify_shipment_result(
                    order.order_number, success=False, error=result.error_message
                )
            except Exception:
                logger.exception("Failed to send failure notification for %s", order.order_number)

    total = completed + failed
    logger.info("Batch complete: %d succeeded, %d failed / %d total", completed, failed, total)

    try:
        await notify_batch_summary(completed, failed, total)
    except Exception:
        logger.exception("Failed to send batch summary notification")

    return 0 if failed == 0 else 1


async def check_orders() -> int:
    settings = get_settings()
    if not settings.supabase_configured:
        logger.error("Supabase credentials not configured")
        return 1

    try:
        orders = await fetch_pending_rentals(ready_only=False)
    except Exception:
        logger.exception("Failed to fetch rentals from Supabase")
        return 1

    logger.info("Pending rentals: %d", len(orders))
    for order in orders:
        raw_name = order.shipping_address.last_name or order.shipping_address.first_name or ""
        name = f"{raw_name[:1]}***" if raw_name else "N/A"
        logger.info("  %s: %s (%s)", order.order_number, name, order.package_size.value)
    return 0


async def run_single_order(order_number: str) -> int:
    """Fetch a single order from Shopify by number and process it through Yamato automation.

    No Supabase interaction — this mode uses Shopify as the source of truth.
    """
    settings = get_settings()
    if not settings.kuroneko_configured:
        logger.error("Kuroneko credentials not configured")
        return 1
    if not settings.shopify_configured:
        logger.error(
            "Shopify credentials not configured. "
            "Set SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET in .env"
        )
        return 1

    clean_number = order_number.lstrip("#")
    logger.info("Fetching order #%s from Shopify...", clean_number)

    try:
        order = await fetch_order_by_number(clean_number)
    except ValueError as exc:
        logger.error("Order not found: %s", exc)
        return 1
    except Exception:
        logger.exception("Failed to fetch order #%s from Shopify", clean_number)
        return 1

    addr = order.shipping_address
    masked_name = f"{addr.last_name[:1]}***" if addr.last_name else "N/A"
    logger.info(
        "Processing order %s — %s (postal: %s)",
        order.order_number,
        masked_name,
        addr.postal_code,
    )

    try:
        result = await process_shipment(order)
    except Exception:
        logger.exception("Shipment processing crashed for order %s", order.order_number)
        return 1

    if result.status.value == "completed":
        logger.info("Completed. QR: %s", result.qr_code_path)
        if settings.line_notify_configured:
            try:
                await notify_shipment_result(
                    order.order_number, success=True, qr_code_path=result.qr_code_path
                )
            except Exception:
                logger.exception("Failed to send LINE notification")
        return 0
    else:
        logger.error("Failed: %s", result.error_message)
        if settings.line_notify_configured:
            try:
                await notify_shipment_result(
                    order.order_number, success=False, error=result.error_message
                )
            except Exception:
                logger.exception("Failed to send LINE notification")
        return 1


async def run_manual_test(payload_path: str | None = None) -> int:
    """Run Yamato automation with a manual JSON payload. No DB updates."""
    settings = get_settings()
    if not settings.kuroneko_configured:
        logger.error("Kuroneko credentials not configured")
        return 1

    if payload_path:
        data = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    else:
        logger.info("No payload file given; using built-in test payload")
        data = {}

    order = RentalOrder(
        order_id=data.get("order_id", "manual-test"),
        order_number=data.get("order_number", "#TEST"),
        shipping_address=ShippingAddress(
            last_name=data.get("last_name", "テスト"),
            first_name=data.get("first_name", "太郎"),
            postal_code=data.get("postal_code", "1500001"),
            province=data.get("prefecture", ""),
            city=data.get("city", ""),
            address1=data.get("address1", ""),
            address2=data.get("address2", ""),
            phone=data.get("phone", "09012345678"),
            building=data.get("building", ""),
        ),
        items=[OrderItem(title=data.get("product_name", "レンタル機器"), quantity=1)],
        package_size=PackageSize(data.get("package_size", settings.default_package_size)),
        delivery_date=data.get("delivery_date", ""),
        delivery_time=DeliveryTimeSlot(data.get("delivery_time", "0")),
        customer_email=data.get("customer_email", ""),
    )

    logger.info("Manual test: order=%s, recipient=%s %s, postal=%s, addr1=%s",
                order.order_number, order.shipping_address.last_name,
                order.shipping_address.first_name, order.shipping_address.postal_code,
                order.shipping_address.address1)

    result = await process_shipment(order)
    logger.info("Result: status=%s, error=%s, qr=%s",
                result.status.value, result.error_message or "(none)", result.qr_code_path or "(none)")
    return 0 if result.status.value == "completed" else 1


def _looks_like_order_number(arg: str) -> bool:
    """Return True if the argument looks like an order number (digits, optionally prefixed with #)."""
    return arg.lstrip("#").isdigit()


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "ship"

    # `python ship.py 2011` or `python ship.py #2011` — order number mode
    if _looks_like_order_number(command):
        code = asyncio.run(run_single_order(command))
    elif command == "ship":
        code = asyncio.run(run_shipment_batch())
    elif command == "check":
        code = asyncio.run(check_orders())
    elif command == "test":
        payload_path = sys.argv[2] if len(sys.argv) > 2 else None
        code = asyncio.run(run_manual_test(payload_path))
    elif command == "health":
        settings = get_settings()
        logger.info("Configuration:")
        logger.info("  Supabase: %s", "configured" if settings.supabase_configured else "NOT SET")
        logger.info("  Kuroneko: %s", "configured" if settings.kuroneko_configured else "NOT SET")
        logger.info("  Shopify: %s", "configured" if settings.shopify_configured else "NOT SET")
        logger.info("  LINE Notify: %s", "configured" if settings.line_notify_configured else "NOT SET")
        code = 0
    else:
        print("Usage: python -m scripts.ship [<order_number>|ship|check|health|test [payload.json]]")
        print("  <order_number> - Shopifyから注文を取得しヤマト自動入力 (例: 2011)")
        print("  ship   - Supabase上の発送対象(rentals)を処理 (デフォルト)")
        print("  check  - Supabase上のpending rentalsを一覧表示(処理なし)")
        print("  test   - Manual test with JSON payload (no DB updates)")
        print("  health - Check configuration status")
        code = 2

    sys.exit(code)


if __name__ == "__main__":
    main()
