import httpx

from scripts.config import get_settings
from scripts.models import OrderItem, PackageSize, ShippingAddress, ShopifyOrder

UNFULFILLED_ORDERS_QUERY = """
{
  orders(first: 50, query: "fulfillment_status:unfulfilled") {
    edges {
      node {
        id
        name
        shippingAddress {
          firstName
          lastName
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
            }
          }
        }
      }
    }
  }
}
"""


PACKAGE_SIZE_THRESHOLDS: list[tuple[int, PackageSize]] = [
    (1, PackageSize.S),
    (3, PackageSize.M),
    (5, PackageSize.L),
]


def _determine_package_size(items: list[OrderItem]) -> PackageSize:
    total_quantity = sum(item.quantity for item in items)
    for threshold, size in PACKAGE_SIZE_THRESHOLDS:
        if total_quantity <= threshold:
            return size
    return PackageSize.LL


SHOPIFY_API_VERSION = "2025-10"
SHOPIFY_REQUEST_TIMEOUT = 30.0


async def _fetch_access_token(client: httpx.AsyncClient, store_url: str, client_id: str, client_secret: str) -> str:
    token_url = f"https://{store_url}/admin/oauth/access_token"
    response = await client.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=SHOPIFY_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    token_data = response.json()
    if "access_token" not in token_data:
        raise ValueError(f"access_token not in response: {token_data}")
    return token_data["access_token"]


async def fetch_unfulfilled_orders() -> list[ShopifyOrder]:
    settings = get_settings()
    if not settings.shopify_configured:
        return []

    async with httpx.AsyncClient() as client:
        access_token = await _fetch_access_token(
            client,
            settings.shopify_store_url,
            settings.shopify_client_id,
            settings.shopify_client_secret,
        )

        url = f"https://{settings.shopify_store_url}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": access_token,
        }

        response = await client.post(
            url,
            json={"query": UNFULFILLED_ORDERS_QUERY},
            headers=headers,
            timeout=SHOPIFY_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

    orders: list[ShopifyOrder] = []
    edges = data.get("data", {}).get("orders", {}).get("edges", [])

    for edge in edges:
        node = edge["node"]
        shipping_addr = node.get("shippingAddress")
        if not shipping_addr:
            continue

        items = [
            OrderItem(
                title=item_edge["node"]["title"],
                quantity=item_edge["node"]["quantity"],
            )
            for item_edge in node.get("lineItems", {}).get("edges", [])
        ]

        address = ShippingAddress(
            last_name=shipping_addr.get("lastName", ""),
            first_name=shipping_addr.get("firstName", ""),
            postal_code=shipping_addr.get("zip", ""),
            province=shipping_addr.get("province", ""),
            city=shipping_addr.get("city", ""),
            address1=shipping_addr.get("address1", ""),
            address2=shipping_addr.get("address2", ""),
            phone=shipping_addr.get("phone", ""),
        )

        order = ShopifyOrder(
            order_id=node["id"],
            order_number=node["name"],
            shipping_address=address,
            items=items,
            package_size=_determine_package_size(items),
        )
        orders.append(order)

    return orders
