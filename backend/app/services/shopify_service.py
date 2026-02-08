import httpx
from app.config import get_settings
from app.models.order import ShopifyOrder, ShippingAddress, OrderItem, PackageSize

UNFULFILLED_ORDERS_QUERY = """
{
  orders(first: 50, query: "fulfillment_status:unfulfilled") {
    edges {
      node {
        id
        name
        shippingAddress {
          name
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


def _determine_package_size(items: list[OrderItem]) -> PackageSize:
    total_quantity = sum(item.quantity for item in items)
    if total_quantity <= 1:
        return PackageSize.S
    elif total_quantity <= 3:
        return PackageSize.M
    elif total_quantity <= 5:
        return PackageSize.L
    return PackageSize.LL


async def fetch_unfulfilled_orders() -> list[ShopifyOrder]:
    settings = get_settings()
    if not settings.shopify_store_url or not settings.shopify_access_token:
        return []

    url = f"https://{settings.shopify_store_url}/admin/api/2025-01/graphql.json"
    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": settings.shopify_access_token,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={"query": UNFULFILLED_ORDERS_QUERY},
            headers=headers,
            timeout=30.0,
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
            name=shipping_addr.get("name", ""),
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
