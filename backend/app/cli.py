import asyncio
import sys
from datetime import datetime

from app.config import get_settings
from app.services.shopify_service import fetch_unfulfilled_orders
from app.services.yamato_automation import process_shipment


async def run_shipment_batch() -> int:
    """Fetch unfulfilled Shopify orders and process each through Yamato automation."""
    settings = get_settings()
    print(f"[{datetime.now().isoformat()}] Starting shipment batch...")

    if not settings.shopify_configured:
        print("ERROR: Shopify credentials not configured.")
        print("Set SHOPIFY_STORE_URL and SHOPIFY_ACCESS_TOKEN in .env or environment.")
        return 1

    try:
        orders = await fetch_unfulfilled_orders()
    except Exception as exc:
        print(f"ERROR: Failed to fetch orders: {exc}")
        return 1
    if not orders:
        print("No unfulfilled orders found. Nothing to process.")
        return 0

    print(f"Found {len(orders)} unfulfilled order(s).")
    results = []

    for order in orders:
        addr = order.shipping_address
        print(f"\nProcessing order {order.order_number}...")
        if addr:
            print(f"  Recipient: {addr.last_name[:1]}***")
            print(f"  Address: {addr.province}{addr.city}***")
        print(f"  Package size: {order.package_size.value}")

        result = await process_shipment(order)
        results.append(result)

        if result.status.value == "completed":
            print(f"  -> Completed. QR: {result.qr_code_path}")
        else:
            print(f"  -> Failed: {result.error_message}")

    completed = sum(1 for r in results if r.status.value == "completed")
    failed = sum(1 for r in results if r.status.value == "failed")
    print(f"\nBatch complete: {completed} succeeded, {failed} failed out of {len(results)} total.")

    return 0 if failed == 0 else 1


async def check_orders() -> int:
    """List unfulfilled Shopify orders without processing them."""
    settings = get_settings()
    if not settings.shopify_configured:
        print("ERROR: Shopify credentials not configured.")
        return 1

    try:
        orders = await fetch_unfulfilled_orders()
    except Exception as exc:
        print(f"ERROR: Failed to fetch orders: {exc}")
        return 1
    print(f"Unfulfilled orders: {len(orders)}")
    for order in orders:
        name = (order.shipping_address.last_name[:1] + "***") if order.shipping_address else "N/A"
        print(f"  {order.order_number}: {name} ({order.package_size.value})")
    return 0


def main() -> None:
    """CLI entrypoint dispatching to ship, check, or health subcommands."""
    command = sys.argv[1] if len(sys.argv) > 1 else "ship"

    if command == "ship":
        code = asyncio.run(run_shipment_batch())
    elif command == "check":
        code = asyncio.run(check_orders())
    elif command == "health":
        settings = get_settings()
        print("Configuration:")
        print(f"  Shopify URL: {'configured' if settings.shopify_store_url else 'NOT SET'}")
        print(f"  Shopify Token: {'configured' if settings.shopify_access_token else 'NOT SET'}")
        print(f"  Headless: {settings.headless_browser}")
        print(f"  Auth State: {settings.auth_state_path}")
        code = 0
    else:
        print("Usage: python -m app.cli [ship|check|health]")
        print("  ship   - Process all unfulfilled orders (default)")
        print("  check  - List unfulfilled orders without processing")
        print("  health - Check configuration status")
        code = 2

    sys.exit(code)


if __name__ == "__main__":
    main()
