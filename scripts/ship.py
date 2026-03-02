import asyncio
import logging
import sys
from datetime import datetime

from scripts.config import get_settings
from scripts.notify import notify_batch_summary, notify_shipment_result
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

        result = await process_shipment(order)

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

    await notify_batch_summary(completed, failed, total)

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


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "ship"

    if command == "ship":
        code = asyncio.run(run_shipment_batch())
    elif command == "check":
        code = asyncio.run(check_orders())
    elif command == "health":
        settings = get_settings()
        logger.info("Configuration:")
        logger.info("  Supabase: %s", "configured" if settings.supabase_configured else "NOT SET")
        logger.info("  Kuroneko: %s", "configured" if settings.kuroneko_configured else "NOT SET")
        logger.info("  LINE Notify: %s", "configured" if settings.line_notify_configured else "NOT SET")
        code = 0
    else:
        print("Usage: python -m scripts.ship [ship|check|health]")
        print("  ship   - Supabase上の発送対象(rentals)を処理 (デフォルト)")
        print("  check  - Supabase上のpending rentalsを一覧表示(処理なし)")
        print("  health - Check configuration status")
        code = 2

    sys.exit(code)


if __name__ == "__main__":
    main()
