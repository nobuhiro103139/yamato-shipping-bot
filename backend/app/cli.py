import asyncio
import sys
from datetime import datetime

from app.config import get_settings
from app.services.yamato_agent import load_shipments, process_shipment


async def run_shipment_batch() -> int:
    """Load shipments from JSON and process each through Browser Use agent."""
    settings = get_settings()
    print(f"[{datetime.now().isoformat()}] Starting shipment batch...")

    shipments = load_shipments(settings.shipments_path)
    if not shipments:
        print(f"No shipments found in {settings.shipments_path}")
        return 0

    print(f"Found {len(shipments)} shipment(s) to process.")
    results = []

    for shipment in shipments:
        initial = shipment.recipient_last_name[:1] if shipment.recipient_last_name else "?"
        masked_name = f"{initial}***"
        print(f"\nProcessing: {masked_name}")
        print(f"  Package: {shipment.package_size_label}")

        result = await process_shipment(shipment)
        results.append(result)

        if result.status.value == "completed":
            print("  -> Completed")
        else:
            print(f"  -> Failed: {result.error_message}")

    completed = sum(1 for r in results if r.status.value == "completed")
    failed = sum(1 for r in results if r.status.value == "failed")
    print(f"\nBatch complete: {completed} succeeded, {failed} failed out of {len(results)} total.")

    return 0 if failed == 0 else 1


async def run_from_shopify() -> int:
    """Fetch unfulfilled orders from Shopify and process via Browser Use agent."""
    from app.models.order import Shipment
    from app.services.shopify_service import fetch_unfulfilled_orders

    settings = get_settings()
    print(f"[{datetime.now().isoformat()}] Fetching orders from Shopify...")

    if not settings.shopify_configured:
        print("ERROR: Shopify credentials not configured.")
        print("Set SHOPIFY_STORE_URL and SHOPIFY_ACCESS_TOKEN in .env")
        return 1

    try:
        orders = await fetch_unfulfilled_orders()
    except Exception as exc:
        print(f"ERROR: Failed to fetch orders: {exc}")
        return 1

    if not orders:
        print("No unfulfilled orders found.")
        return 0

    print(f"Found {len(orders)} unfulfilled order(s).")
    results = []

    for order in orders:
        addr = order.shipping_address
        phone = addr.phone.replace("+81 ", "0").replace("+81", "0").replace("-", "")
        shipment = Shipment(
            recipient_last_name=addr.last_name,
            recipient_first_name=addr.first_name,
            recipient_postal_code=addr.postal_code,
            recipient_phone=phone,
            recipient_email=order.customer_email,
            recipient_banchi=addr.banchi or addr.address1,
            recipient_building=addr.building or addr.address2,
            recipient_chome=addr.chome,
            recipient_go=addr.go,
            product_name=", ".join(item.title for item in order.items)[:17],
            package_size=order.package_size,
            delivery_date=order.delivery_date,
            order_id=order.order_number,
        )

        masked_name = f"{addr.last_name[:1]}***" if addr.last_name else "N/A"
        print(f"\nProcessing order {order.order_number}: {masked_name}")

        result = await process_shipment(shipment)
        results.append(result)

        if result.status.value == "completed":
            print("  -> Completed")
        else:
            print(f"  -> Failed: {result.error_message}")

    completed = sum(1 for r in results if r.status.value == "completed")
    failed = sum(1 for r in results if r.status.value == "failed")
    print(f"\nBatch complete: {completed} succeeded, {failed} failed out of {len(results)} total.")

    return 0 if failed == 0 else 1


async def check_shipments() -> int:
    """List pending shipments from JSON without processing."""
    settings = get_settings()
    shipments = load_shipments(settings.shipments_path)
    print(f"Pending shipments in {settings.shipments_path}: {len(shipments)}")
    for s in shipments:
        initial = s.recipient_last_name[:1] if s.recipient_last_name else "?"
        masked = f"{initial}***"
        print(f"  {s.identifier}: {masked} ({s.package_size_label})")
        if s.delivery_date:
            print(f"    Delivery: {s.delivery_date} {s.delivery_time}")
    return 0


def main() -> None:
    """CLI entrypoint: ship, ship-shopify, check, health."""
    command = sys.argv[1] if len(sys.argv) > 1 else "ship"

    if command == "ship":
        code = asyncio.run(run_shipment_batch())
    elif command == "ship-shopify":
        code = asyncio.run(run_from_shopify())
    elif command == "check":
        code = asyncio.run(check_shipments())
    elif command == "health":
        settings = get_settings()
        print("Configuration:")
        print(f"  LLM Provider: {settings.llm_provider}")
        print(f"  LLM Model: {settings.llm_model}")
        print(f"  LLM API Key: {'configured' if settings.llm_api_key else 'NOT SET'}")
        print(f"  Shipments Path: {settings.shipments_path}")
        print(f"  Shopify URL: {'configured' if settings.shopify_store_url else 'NOT SET'}")
        print(f"  Shopify Token: {'configured' if settings.shopify_access_token else 'NOT SET'}")
        print(f"  Kuroneko ID: {'configured' if settings.kuroneko_login_id else 'NOT SET'}")
        print(f"  Headless: {settings.headless_browser}")
        print(f"  Auth State: {settings.auth_state_path}")
        code = 0
    else:
        print("Usage: python -m app.cli [ship|ship-shopify|check|health]")
        print("  ship          - Process shipments from shipments.json (default)")
        print("  ship-shopify  - Fetch from Shopify API and process")
        print("  check         - List pending shipments without processing")
        print("  health        - Check configuration status")
        code = 2

    sys.exit(code)


if __name__ == "__main__":
    main()
