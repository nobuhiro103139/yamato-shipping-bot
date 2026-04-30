"""Tests for the B2 cloud CSV generator.

Validates row construction against the committed sample CSVs
(``b2cloud_20260429_imakiire.csv``, ``b2cloud_20260429_kaneshiro.csv``).
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import b2_cloud
from scripts.b2_cloud import (
    HEADER,
    _format_delivery_date,
    _format_phone,
    _format_postal_code,
    append_b2_csv,
    build_b2_row,
)
from scripts.config import Settings
from scripts.models import (
    DeliveryTimeSlot,
    OrderItem,
    PackageSize,
    RentalOrder,
    ShippingAddress,
)


def _settings(**overrides) -> Settings:
    base = dict(
        sender_name="ＴｅｃｈＲｅｎｔａｌ",
        sender_postal_code="658-0003",
        sender_address1="兵庫県神戸市東灘区本山北町5-10-28-1",
        sender_address2="",
        sender_phone="080-3421-5105",
        b2_billing_customer_code="080342151059",
        b2_freight_management_number="01",
    )
    base.update(overrides)
    return Settings(**base)


def _imakiire_order() -> RentalOrder:
    return RentalOrder(
        order_id="rental-imakiire",
        order_number="#TEST-001",
        shipping_address=ShippingAddress(
            last_name="今給黎",
            first_name="ちひろ",
            postal_code="2140039",
            province="神奈川県",
            city="川崎市多摩区",
            address1="栗谷3-2-11",
            address2="リズ生田 404号室",
            phone="07019447217",
        ),
        items=[OrderItem(title="スマートフォン", quantity=1)],
        package_size=PackageSize.COMPACT,
        delivery_date="20260502",
        delivery_time=DeliveryTimeSlot.PM_14_16,
    )


def _kaneshiro_order() -> RentalOrder:
    return RentalOrder(
        order_id="rental-kaneshiro",
        order_number="#TEST-002",
        shipping_address=ShippingAddress(
            last_name="金城",
            first_name="多喜子",
            postal_code="188-0004",
            province="東京都",
            city="西東京市",
            address1="西原町4-10",
            address2="第三住宅4-307号",
            phone="090-7415-1645",
        ),
        items=[OrderItem(title="スマートフォン", quantity=1)],
        package_size=PackageSize.COMPACT,
        delivery_date="20260501",
        delivery_time=DeliveryTimeSlot.PM_16_18,
    )


def test_header_is_95_columns():
    assert len(HEADER) == 95


def test_format_postal_code():
    assert _format_postal_code("2140039") == "214-0039"
    assert _format_postal_code("214-0039") == "214-0039"
    assert _format_postal_code("") == ""


def test_format_phone_11_digit_mobile():
    assert _format_phone("07019447217") == "070-1944-7217"


def test_format_phone_already_hyphenated():
    assert _format_phone("080-3421-5105") == "080-3421-5105"


def test_format_phone_10_digit_tokyo():
    assert _format_phone("0312345678") == "03-1234-5678"


def test_format_delivery_date():
    assert _format_delivery_date("20260502") == "2026/05/02"
    assert _format_delivery_date("") == ""
    assert _format_delivery_date("invalid") == ""


def test_build_row_matches_imakiire_sample():
    row = build_b2_row(_imakiire_order(), _settings())
    assert len(row) == 95
    assert row[1] == "0"  # 送り状種類
    assert row[5] == "2026/05/02"  # お届け予定日
    assert row[6] == "1416"  # 配達時間帯
    assert row[8] == "070-1944-7217"
    assert row[10] == "214-0039"
    assert row[11] == "神奈川県川崎市多摩区栗谷3-2-11"
    assert row[12] == "リズ生田 404号室"
    assert row[15] == "今給黎 ちひろ"
    assert row[19] == "080-3421-5105"
    assert row[21] == "658-0003"
    assert row[22] == "兵庫県神戸市東灘区本山北町5-10-28-1"
    assert row[24] == "ＴｅｃｈＲｅｎｔａｌ"
    assert row[27] == "スマートフォン"
    assert row[30] == "精密機械"
    assert row[39] == "080342151059"
    assert row[41] == "01"


def test_build_row_kaneshiro_time_slot():
    row = build_b2_row(_kaneshiro_order(), _settings())
    assert row[6] == "1618"
    assert row[5] == "2026/05/01"
    assert row[15] == "金城 多喜子"


def test_delivery_time_none_means_empty():
    order = _imakiire_order()
    order.delivery_time = DeliveryTimeSlot.NONE
    row = build_b2_row(order, _settings())
    assert row[6] == ""


def test_append_b2_csv_creates_file_with_header_and_crlf(tmp_path: Path):
    settings = _settings(b2_output_dir=str(tmp_path))
    out = append_b2_csv([_imakiire_order()], settings)

    raw = out.read_bytes()
    assert raw.endswith(b"\r\n")
    # Two rows = header + data; both end with CRLF
    assert raw.count(b"\r\n") == 2

    text = raw.decode("cp932")
    rows = list(csv.reader(text.splitlines()))
    assert len(rows) == 2
    assert tuple(rows[0]) == HEADER
    assert rows[1][1] == "0"
    assert rows[1][15] == "今給黎 ちひろ"


def test_append_b2_csv_appends_without_duplicate_header(tmp_path: Path):
    settings = _settings(b2_output_dir=str(tmp_path))
    append_b2_csv([_imakiire_order()], settings)
    append_b2_csv([_kaneshiro_order()], settings)

    out = b2_cloud.daily_output_path(settings.b2_output_dir)
    text = out.read_bytes().decode("cp932")
    rows = list(csv.reader(text.splitlines()))
    assert len(rows) == 3  # header + 2 data
    assert tuple(rows[0]) == HEADER
    assert rows[1][15] == "今給黎 ちひろ"
    assert rows[2][15] == "金城 多喜子"


def test_append_b2_csv_writes_shift_jis(tmp_path: Path):
    settings = _settings(b2_output_dir=str(tmp_path))
    out = append_b2_csv([_imakiire_order()], settings)
    raw = out.read_bytes()
    # Should NOT decode as pure ASCII / UTF-8 (Japanese bytes are SJIS)
    assert b"\x90\x5f\x96\x5b\x8b\x40\x8a\x42" not in raw  # garbage check
    text = raw.decode("cp932")
    assert "今給黎" in text
    assert "ＴｅｃｈＲｅｎｔａｌ" in text
    # Must NOT decode as UTF-8 cleanly when it contains Japanese
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")


def test_append_b2_csv_empty_orders_raises(tmp_path: Path):
    settings = _settings(b2_output_dir=str(tmp_path))
    with pytest.raises(ValueError):
        append_b2_csv([], settings)


def test_full_csv_field_layout_matches_committed_sample():
    """Compare row layout against the actual committed sample CSV."""
    sample = Path("b2cloud_20260429_imakiire.csv")
    if not sample.exists():
        pytest.skip("sample CSV not present in working directory")

    text = sample.read_bytes().decode("cp932")
    rows = list(csv.reader(text.splitlines()))
    sample_data = rows[1]

    # Freeze "today" at the sample's 出荷予定日 so 列5 matches
    with patch.object(b2_cloud, "_today_jst", return_value="2026/04/29"):
        built = build_b2_row(_imakiire_order(), _settings())

    # Compare every column we populate; the rest should both be empty
    for i in range(95):
        assert built[i] == sample_data[i], f"column {i+1} ({HEADER[i]}) mismatch"
