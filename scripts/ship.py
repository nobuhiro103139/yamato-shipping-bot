import asyncio
import logging
import sys
from datetime import datetime

from scripts.config import get_settings
from scripts.notify import notify_batch_summary, notify_shipment_result
from scripts.shopify_client import fetch_unfulfilled_orders
from scripts.yamato_automation import process_shipment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_shipment_batch() -> int:
    settings = get_settings()
    logger.info("Starting shipment batch at %s", datetime.now().isoformat())

    if not settings.shopify_configured:
        logger.error("Shopify credentials not configured")
        return 1

    try:
        orders = await fetch_unfulfilled_orders()
    except Exception:
        logger.exception("Failed to fetch orders")
        return 1

    if not orders:
        logger.info("No unfulfilled orders found")
        return 0

    logger.info("Found %d unfulfilled order(s)", len(orders))
    results = []

    for order in orders:
        addr = order.shipping_address
        raw_name = addr.last_name or addr.first_name or ""
        masked_name = f"{raw_name[:1]}***" if raw_name else "N/A"
        logger.info(
            "Processing %s — %s",
            order.order_number,
            masked_name,
        )

        result = await process_shipment(order)
        results.append(result)

        if result.status.value == "completed":
            logger.info("  -> Completed. QR: %s", result.qr_code_path)
            await notify_shipment_result(
                order.order_number, success=True, qr_code_path=result.qr_code_path
            )
        else:
            logger.error("  -> Failed: %s", result.error_message)
            await notify_shipment_result(
                order.order_number, success=False, error=result.error_message
            )

    completed = sum(1 for r in results if r.status.value == "completed")
    failed = sum(1 for r in results if r.status.value == "failed")
    logger.info("Batch complete: %d succeeded, %d failed / %d total", completed, failed, len(results))

    await notify_batch_summary(completed, failed, len(results))

    return 0 if failed == 0 else 1


async def check_orders() -> int:
    settings = get_settings()
    if not settings.shopify_configured:
        logger.error("Shopify credentials not configured")
        return 1

    try:
        orders = await fetch_unfulfilled_orders()
    except Exception:
        logger.exception("Failed to fetch orders")
        return 1

    logger.info("Unfulfilled orders: %d", len(orders))
    for order in orders:
        raw_name = order.shipping_address.last_name or order.shipping_address.first_name or ""
        name = f"{raw_name[:1]}***" if raw_name else "N/A"
        logger.info("  %s: %s (%s)", order.order_number, name, order.package_size.value)
    return 0


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "ship"

    if command == "ship":
        code = asyncio.run(run_shipment_batch())
    elif command == "check":
        code = asyncio.run(check_orders())
    elif command == "health":
        settings = get_settings()
        logger.info("Configuration:")
        logger.info("  Shopify: %s", "configured" if settings.shopify_configured else "NOT SET")
        logger.info("  Kuroneko: %s", "configured" if settings.kuroneko_configured else "NOT SET")
        logger.info("  LINE Notify: %s", "configured" if settings.line_notify_configured else "NOT SET")
        code = 0
    else:
        print("Usage: python -m scripts.ship [ship|check|health]")
        print("  ship   - Process all unfulfilled orders (default)")
        print("  check  - List unfulfilled orders without processing")
        print("  health - Check configuration status")
        code = 2

    sys.exit(code)


if __name__ == "__main__":
    main()
