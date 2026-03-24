"""Shopify GraphQL client for fetching order shipping addresses.

Uses Client Credentials Grant (NOB-41) to obtain a short-lived access token,
then queries the Admin GraphQL API for order details by order number.

Falls back to curl subprocess when httpx encounters TLS issues on some macOS
environments (LibreSSL / system OpenSSL mismatch).
"""

import json
import logging
import ssl
import subprocess
import time

import certifi
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

SHOPIFY_REQUEST_TIMEOUT = 30.0

# Module-level token cache
_token_cache: dict[str, object] = {"token": None, "expires_at": 0.0}

# Mapping from Shopify customAttribute keys to delivery time slots
# Supports both Japanese label format and HH:MM~HH:MM format
_TIME_SLOT_MAP: dict[str, DeliveryTimeSlot] = {
    "午前中": DeliveryTimeSlot.MORNING,
    "14時〜16時": DeliveryTimeSlot.PM_14_16,
    "16時〜18時": DeliveryTimeSlot.PM_16_18,
    "18時〜20時": DeliveryTimeSlot.PM_18_20,
    "19時〜21時": DeliveryTimeSlot.PM_19_21,
    "8:00~12:00": DeliveryTimeSlot.MORNING,
    "14:00~16:00": DeliveryTimeSlot.PM_14_16,
    "16:00~18:00": DeliveryTimeSlot.PM_16_18,
    "18:00~20:00": DeliveryTimeSlot.PM_18_20,
    "19:00~21:00": DeliveryTimeSlot.PM_19_21,
}

ORDERS_QUERY = """
query orderByNumber($query: String!) {
  orders(first: 1, query: $query) {
    edges {
      node {
        id
        name
        note
        customAttributes {
          key
          value
        }
        shippingAddress {
          lastName
          firstName
          zip
          province
          city
          address1
          address2
          phone
        }
        lineItems(first: 10) {
          edges {
            node {
              title
              quantity
              customAttributes {
                key
                value
              }
            }
          }
        }
      }
    }
  }
}
"""


def _curl_post_json(url: str, *, headers: dict[str, str] | None = None,
                    json_body: dict | None = None,
                    form_data: dict[str, str] | None = None) -> dict:
    """POST via curl subprocess as TLS fallback. Returns parsed JSON."""
    cmd = [
        "curl", "-sS", "--fail-with-body",
        "--cacert", certifi.where(),
        "-X", "POST", url,
    ]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]

    if json_body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(json_body)]
    elif form_data is not None:
        for k, v in form_data.items():
            cmd += ["-d", f"{k}={v}"]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=SHOPIFY_REQUEST_TIMEOUT)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed (rc={result.returncode}): {result.stderr[:500]}")
    return json.loads(result.stdout)


async def _httpx_post_json(url: str, *, headers: dict[str, str] | None = None,
                           json_body: dict | None = None,
                           form_data: dict[str, str] | None = None) -> dict:
    """POST via httpx with certifi, falling back to curl on TLS errors."""
    try:
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        async with httpx.AsyncClient(verify=ssl_ctx) as client:
            if json_body is not None:
                resp = await client.post(url, headers=headers, json=json_body,
                                         timeout=SHOPIFY_REQUEST_TIMEOUT)
            else:
                resp = await client.post(url, headers=headers, data=form_data,
                                         timeout=SHOPIFY_REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
    except (httpx.ConnectError, httpx.ReadError, OSError) as exc:
        logger.warning("httpx TLS failed (%s), falling back to curl", exc)
        return _curl_post_json(url, headers=headers, json_body=json_body, form_data=form_data)


async def _get_access_token() -> str:
    """Obtain a Shopify access token via Client Credentials Grant.

    Tokens are cached until 5 minutes before expiry (24h default).
    """
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return str(_token_cache["token"])

    settings = get_settings()
    url = f"https://{settings.shopify_store}.myshopify.com/admin/oauth/access_token"

    data = await _httpx_post_json(url, form_data={
        "client_id": settings.shopify_client_id,
        "client_secret": settings.shopify_client_secret,
        "grant_type": "client_credentials",
    })

    token = data.get("access_token")
    if not token:
        raise RuntimeError("Shopify token response missing access_token field")

    expires_in = int(data.get("expires_in", 86400))
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + expires_in - 300

    logger.info("Obtained Shopify access token (expires in %ds)", expires_in)
    return str(token)


def _parse_custom_attributes(
    line_items_edges: list[dict],
    order_attrs: list[dict] | None = None,
) -> dict[str, str]:
    """Extract customAttributes from order-level and line items into a flat dict.

    Shopify stores rental metadata (開始日, 終了日, 配達指定時刻, etc.)
    as customAttributes on orders and/or line items.
    Order-level attributes take precedence.
    """
    attrs: dict[str, str] = {}
    # Line item level attributes
    for edge in line_items_edges:
        for attr in edge.get("node", {}).get("customAttributes", []) or []:
            key = attr.get("key", "")
            value = attr.get("value", "")
            if key and value:
                attrs[key] = value
    # Order-level attributes (override line item if same key)
    for attr in order_attrs or []:
        key = attr.get("key", "")
        value = attr.get("value", "")
        if key and value:
            attrs[key] = value
    return attrs


def _resolve_delivery_time(attrs: dict[str, str]) -> DeliveryTimeSlot:
    """Map customAttribute time string to DeliveryTimeSlot enum.

    Checks multiple possible keys: 配達指定時刻, 配達時間の設定(必須), delivery_time.
    Supports comma-separated values (takes the first matching slot).
    """
    raw = (
        attrs.get("配達指定時刻")
        or attrs.get("配達時間の設定(必須)")
        or attrs.get("delivery_time")
        or ""
    )
    # Direct match
    slot = _TIME_SLOT_MAP.get(raw.strip())
    if slot:
        return slot

    # Comma-separated: try each part (first match wins)
    if "," in raw:
        for part in raw.split(","):
            part = part.strip()
            slot = _TIME_SLOT_MAP.get(part)
            if slot:
                logger.info("Resolved delivery time from multi-value '%s' -> %s", raw, part)
                return slot

    if raw:
        logger.warning("Unrecognized delivery time value: '%s'", raw)
    return DeliveryTimeSlot.NONE


def _resolve_delivery_date(attrs: dict[str, str]) -> str:
    """Extract delivery date from customAttributes, return YYYYMMDD or empty.

    Checks multiple possible keys: 開始日, Start, _start_iso8601, delivery_date.
    Accepts YYYY-MM-DD, YYYYMMDD, or ISO8601 datetime formats.
    """
    raw = (
        attrs.get("開始日")
        or attrs.get("Start")
        or attrs.get("_start_iso8601")
        or attrs.get("delivery_date")
        or ""
    )
    # Strip time portion if ISO8601 datetime (e.g., "2026-03-28T00:00:00+09:00")
    if "T" in raw:
        raw = raw.split("T")[0]
    # Accept YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD, or YYYYMMDD
    clean = raw.replace("-", "").replace("/", "").replace(".", "")
    if len(clean) == 8 and clean.isdigit():
        return clean
    return ""


async def fetch_order_by_number(order_number: str) -> RentalOrder:
    """Fetch a Shopify order by its display number and return a RentalOrder.

    Args:
        order_number: The order number (e.g. "2011" or "#2011").
                      The leading '#' is stripped if present.

    Raises:
        ValueError: If the order is not found or has no shipping address.
        RuntimeError: If the Shopify API call fails.
    """
    settings = get_settings()
    if not settings.shopify_configured:
        raise RuntimeError(
            "Shopify credentials not configured. "
            "Set SHOPIFY_STORE, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET in .env"
        )

    clean_number = order_number.lstrip("#")
    token = await _get_access_token()

    graphql_url = f"https://{settings.shopify_store}.myshopify.com/admin/api/2024-10/graphql.json"
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }

    result = await _httpx_post_json(
        graphql_url,
        headers=headers,
        json_body={
            "query": ORDERS_QUERY,
            "variables": {"query": f"name:#{clean_number}"},
        },
    )

    errors = result.get("errors")
    if errors:
        raise RuntimeError(f"Shopify GraphQL error: {errors}")

    edges = result.get("data", {}).get("orders", {}).get("edges", [])
    if not edges:
        raise ValueError(f"Order #{clean_number} not found in Shopify")

    node = edges[0]["node"]
    addr = node.get("shippingAddress")
    if not addr:
        raise ValueError(f"Order #{clean_number} has no shipping address")

    shipping_address = ShippingAddress(
        last_name=addr.get("lastName") or "",
        first_name=addr.get("firstName") or "",
        postal_code=(addr.get("zip") or "").replace("-", ""),
        province=addr.get("province") or "",
        city=addr.get("city") or "",
        address1=addr.get("address1") or "",
        address2=addr.get("address2") or "",
        phone=addr.get("phone") or "",
    )

    line_items_edges = node.get("lineItems", {}).get("edges", [])
    line_items = [
        OrderItem(
            title=edge["node"]["title"],
            quantity=edge["node"]["quantity"],
        )
        for edge in line_items_edges
    ]
    if not line_items:
        line_items = [OrderItem(title="レンタル機器", quantity=1)]

    # Parse delivery metadata from customAttributes (order-level + line item level)
    order_attrs = node.get("customAttributes") or []
    custom_attrs = _parse_custom_attributes(line_items_edges, order_attrs)
    logger.info("Parsed customAttributes keys: %s", list(custom_attrs.keys()))
    if custom_attrs:
        # ログに値も出す (個人情報でないキーのみ、トークン系は除外)
        skip_keys = {"BTA Token", "_addons_uuid"}
        for k, v in custom_attrs.items():
            if k not in skip_keys:
                logger.info("  attr[%s] = %s", k, v)

    delivery_date = _resolve_delivery_date(custom_attrs)
    delivery_time = _resolve_delivery_time(custom_attrs)

    if delivery_date:
        logger.info("Delivery date from customAttributes: %s", delivery_date)
    else:
        logger.warning("No delivery date found in customAttributes")
    if delivery_time != DeliveryTimeSlot.NONE:
        logger.info("Delivery time from customAttributes: %s", delivery_time.value)
    else:
        logger.warning("No delivery time found in customAttributes")

    display_name = node.get("name", f"#{clean_number}")

    try:
        package_size = PackageSize(settings.default_package_size)
    except ValueError:
        package_size = PackageSize.COMPACT

    order = RentalOrder(
        order_id=f"shopify-{clean_number}",
        order_number=display_name,
        shipping_address=shipping_address,
        items=line_items,
        package_size=package_size,
        delivery_date=delivery_date,
        delivery_time=delivery_time,
    )

    masked_name = f"{shipping_address.last_name[:1]}***" if shipping_address.last_name else "N/A"
    logger.info(
        "Fetched Shopify order %s -> recipient=%s, postal=%s",
        display_name,
        masked_name,
        shipping_address.postal_code,
    )
    return order
