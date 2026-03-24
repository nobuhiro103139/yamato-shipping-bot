"""Unit tests for shopify_client module."""

import pytest

from scripts.shopify_client import (
    _parse_custom_attributes,
    _resolve_delivery_date,
    _resolve_delivery_time,
    _token_cache,
    fetch_order_by_number,
)
from scripts.models import DeliveryTimeSlot


@pytest.fixture(autouse=True)
def _clear_token_cache():
    """Reset token cache between tests."""
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0.0
    yield
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0.0


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Reset settings cache between tests."""
    from scripts.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


MOCK_GRAPHQL_RESPONSE = {
    "data": {
        "orders": {
            "edges": [
                {
                    "node": {
                        "id": "gid://shopify/Order/123",
                        "name": "#2011",
                        "email": "tanaka@example.com",
                        "shippingAddress": {
                            "lastName": "田中",
                            "firstName": "太郎",
                            "zip": "150-0001",
                            "province": "東京都",
                            "city": "渋谷区",
                            "address1": "神宮前1-2-3",
                            "address2": "テストビル101",
                            "phone": "09012345678",
                        },
                        "lineItems": {
                            "edges": [
                                {
                                    "node": {
                                        "title": "iPhone 15 レンタル",
                                        "quantity": 1,
                                        "customAttributes": [
                                            {"key": "開始日", "value": "2026-04-01"},
                                            {"key": "終了日", "value": "2026-04-10"},
                                            {"key": "配達指定時刻", "value": "午前中"},
                                        ],
                                    }
                                }
                            ]
                        },
                    }
                }
            ]
        }
    }
}

MOCK_TOKEN_RESPONSE = {
    "access_token": "test-token-xxx",
    "expires_in": 86400,
    "scope": "read_orders",
}


@pytest.mark.asyncio
async def test_fetch_order_by_number_success(monkeypatch, httpx_mock):
    """Test successful order fetch with customAttributes parsing."""
    monkeypatch.setenv("SHOPIFY_STORE", "test-store")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "test-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "test-secret")

    httpx_mock.add_response(
        url="https://test-store.myshopify.com/admin/oauth/access_token",
        json=MOCK_TOKEN_RESPONSE,
    )
    httpx_mock.add_response(
        url="https://test-store.myshopify.com/admin/api/2024-10/graphql.json",
        json=MOCK_GRAPHQL_RESPONSE,
    )

    order = await fetch_order_by_number("2011")

    assert order.order_number == "#2011"
    assert order.shipping_address.last_name == "田中"
    assert order.shipping_address.first_name == "太郎"
    assert order.shipping_address.postal_code == "1500001"  # hyphen stripped
    assert order.shipping_address.province == "東京都"
    assert order.shipping_address.city == "渋谷区"
    assert order.shipping_address.address1 == "神宮前1-2-3"
    assert order.shipping_address.phone == "09012345678"
    assert order.items[0].title == "iPhone 15 レンタル"
    assert order.order_id == "shopify-2011"
    # customAttributes should be parsed
    assert order.delivery_date == "20260401"
    assert order.delivery_time == DeliveryTimeSlot.MORNING
    assert order.customer_email == "tanaka@example.com"


@pytest.mark.asyncio
async def test_fetch_order_not_found(monkeypatch, httpx_mock):
    """Test error when order is not found."""
    monkeypatch.setenv("SHOPIFY_STORE", "test-store")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "test-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "test-secret")

    httpx_mock.add_response(
        url="https://test-store.myshopify.com/admin/oauth/access_token",
        json=MOCK_TOKEN_RESPONSE,
    )
    httpx_mock.add_response(
        url="https://test-store.myshopify.com/admin/api/2024-10/graphql.json",
        json={"data": {"orders": {"edges": []}}},
    )

    with pytest.raises(ValueError, match="not found"):
        await fetch_order_by_number("9999")


@pytest.mark.asyncio
async def test_fetch_order_no_shipping_address(monkeypatch, httpx_mock):
    """Test error when order has no shipping address."""
    monkeypatch.setenv("SHOPIFY_STORE", "test-store")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "test-id")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "test-secret")

    httpx_mock.add_response(
        url="https://test-store.myshopify.com/admin/oauth/access_token",
        json=MOCK_TOKEN_RESPONSE,
    )
    httpx_mock.add_response(
        url="https://test-store.myshopify.com/admin/api/2024-10/graphql.json",
        json={
            "data": {
                "orders": {
                    "edges": [
                        {
                            "node": {
                                "id": "gid://shopify/Order/456",
                                "name": "#2012",
                                "shippingAddress": None,
                                "lineItems": {"edges": []},
                            }
                        }
                    ]
                }
            }
        },
    )

    with pytest.raises(ValueError, match="no shipping address"):
        await fetch_order_by_number("2012")


@pytest.mark.asyncio
async def test_shopify_not_configured(monkeypatch):
    """Test error when Shopify is not configured."""
    monkeypatch.setenv("SHOPIFY_STORE", "")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "")

    with pytest.raises(RuntimeError, match="not configured"):
        await fetch_order_by_number("2011")


# --- Unit tests for helper functions ---


def test_parse_custom_attributes():
    edges = [
        {
            "node": {
                "title": "Item",
                "quantity": 1,
                "customAttributes": [
                    {"key": "開始日", "value": "2026-04-01"},
                    {"key": "配達指定時刻", "value": "午前中"},
                ],
            }
        }
    ]
    attrs = _parse_custom_attributes(edges)
    assert attrs["開始日"] == "2026-04-01"
    assert attrs["配達指定時刻"] == "午前中"


def test_parse_custom_attributes_empty():
    assert _parse_custom_attributes([]) == {}
    edges = [{"node": {"customAttributes": None}}]
    assert _parse_custom_attributes(edges) == {}


def test_resolve_delivery_date():
    assert _resolve_delivery_date({"開始日": "2026-04-01"}) == "20260401"
    assert _resolve_delivery_date({"開始日": "20260401"}) == "20260401"
    assert _resolve_delivery_date({"開始日": "invalid"}) == ""
    assert _resolve_delivery_date({}) == ""


def test_resolve_delivery_time():
    assert _resolve_delivery_time({"配達指定時刻": "午前中"}) == DeliveryTimeSlot.MORNING
    assert _resolve_delivery_time({"配達指定時刻": "19時〜21時"}) == DeliveryTimeSlot.PM_19_21
    assert _resolve_delivery_time({"配達指定時刻": "不明"}) == DeliveryTimeSlot.NONE
    assert _resolve_delivery_time({}) == DeliveryTimeSlot.NONE
