"""Tests for the B2 cloud CSV generator.

Validates row construction, deduplication, encoding safety, and configuration
validation for the B2 cloud CSV export pipeline.
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
    _read_existing_order_keys,
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


def test_format_phone_plus81_mobile():
    assert _format_phone("+818042127753") == "080-4212-7753"


def test_format_phone_plus81_mobile_without_plus():
    assert _format_phone("819023737233") == "090-2373-7233"


def test_format_phone_10_digit_tokyo():
    assert _format_phone("0312345678") == "03-1234-5678"


def test_format_delivery_date():
    assert _format_delivery_date("20260502") == "2026/05/02"
    assert _format_delivery_date("") == ""
    assert _format_delivery_date("invalid") == ""


def test_build_row_matches_imakiire_sample():
    row = build_b2_row(_imakiire_order(), _settings())
    assert len(row) == 95
    assert row[0] == "#TEST-001"  # お客様管理番号 = order_number (dedup key)
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


def test_full_csv_field_layout_all_95_columns():
    """Regression guard: validate every column of the generated row.

    This test always runs (no external fixture required) and catches
    any accidental shift in the 95-column layout.
    """
    with patch.object(b2_cloud, "_today_jst", return_value="2026/04/29"):
        built = build_b2_row(_imakiire_order(), _settings())

    assert len(built) == 95

    # Columns we actively populate
    expected_populated = {
        0: "#TEST-001",                                   # お客様管理番号 (order_number)
        1: "0",                                          # 送り状種類
        4: "2026/04/29",                                 # 出荷予定日 (frozen)
        5: "2026/05/02",                                 # お届け予定日
        6: "1416",                                       # 配達時間帯
        8: "070-1944-7217",                              # お届け先電話番号
        10: "214-0039",                                  # お届け先郵便番号
        11: "神奈川県川崎市多摩区栗谷3-2-11",            # お届け先住所
        12: "リズ生田 404号室",                           # アパマン名
        15: "今給黎 ちひろ",                              # お届け先名
        19: "080-3421-5105",                             # ご依頼主電話番号
        21: "658-0003",                                  # ご依頼主郵便番号
        22: "兵庫県神戸市東灘区本山北町5-10-28-1",        # ご依頼主住所
        24: "ＴｅｃｈＲｅｎｔａｌ",                       # ご依頼主名
        27: "スマートフォン",                              # 品名１
        30: "精密機械",                                   # 荷扱い１
        39: "080342151059",                              # 請求先顧客コード
        41: "01",                                        # 運賃管理番号
    }

    for col_idx, expected in expected_populated.items():
        assert built[col_idx] == expected, (
            f"column {col_idx + 1} ({HEADER[col_idx]}): "
            f"expected {expected!r}, got {built[col_idx]!r}"
        )

    # All other columns must be empty strings
    for i in range(95):
        if i not in expected_populated:
            assert built[i] == "", (
                f"column {i + 1} ({HEADER[i]}) should be empty, got {built[i]!r}"
            )


# ---------------------------------------------------------------------------
# 重複防止テスト
# ---------------------------------------------------------------------------

def test_append_b2_csv_dedup_skips_already_present_order(tmp_path: Path):
    """同じ注文番号を 2 回追記しても 2 行目は書き込まれない."""
    settings = _settings(b2_output_dir=str(tmp_path))
    append_b2_csv([_imakiire_order()], settings)
    append_b2_csv([_imakiire_order()], settings)  # 重複

    out = b2_cloud.daily_output_path(settings.b2_output_dir)
    text = out.read_bytes().decode("cp932")
    rows = list(csv.reader(text.splitlines()))
    assert len(rows) == 2, "ヘッダー + データ 1 行のみ (重複なし)"


def test_append_b2_csv_dedup_allows_different_orders(tmp_path: Path):
    """別注文番号は同じ日の CSV に両方書き込まれる."""
    settings = _settings(b2_output_dir=str(tmp_path))
    append_b2_csv([_imakiire_order()], settings)
    append_b2_csv([_kaneshiro_order()], settings)

    out = b2_cloud.daily_output_path(settings.b2_output_dir)
    text = out.read_bytes().decode("cp932")
    rows = list(csv.reader(text.splitlines()))
    assert len(rows) == 3  # ヘッダー + 2 件


def test_append_b2_csv_dedup_returns_path_when_all_duplicates(tmp_path: Path):
    """全件重複の場合もパスを返し、ファイルに変更なし."""
    settings = _settings(b2_output_dir=str(tmp_path))
    append_b2_csv([_imakiire_order()], settings)
    original_size = b2_cloud.daily_output_path(settings.b2_output_dir).stat().st_size

    result = append_b2_csv([_imakiire_order()], settings)
    assert result == b2_cloud.daily_output_path(settings.b2_output_dir)
    assert result.stat().st_size == original_size, "ファイルサイズ変化なし"


def test_read_existing_order_keys_returns_set(tmp_path: Path):
    """_read_existing_order_keys が列0 の値をセットで返す."""
    settings = _settings(b2_output_dir=str(tmp_path))
    append_b2_csv([_imakiire_order(), _kaneshiro_order()], settings)
    out = b2_cloud.daily_output_path(settings.b2_output_dir)
    keys = _read_existing_order_keys(out)
    assert "#TEST-001" in keys
    assert "#TEST-002" in keys
    assert HEADER[0] not in keys, "ヘッダー行はキーセットに含まれない"


def test_read_existing_order_keys_nonexistent_file():
    """存在しないファイルを渡すと空セットを返す (クラッシュしない)."""
    keys = _read_existing_order_keys(Path("/nonexistent/path.csv"))
    assert keys == set()


# ---------------------------------------------------------------------------
# B2 必須設定バリデーションテスト
# ---------------------------------------------------------------------------

def test_b2_configured_true_when_both_set():
    s = _settings()
    assert s.b2_configured is True


def test_b2_configured_false_when_billing_missing():
    s = _settings(b2_billing_customer_code="")
    assert s.b2_configured is False


def test_b2_configured_false_when_freight_missing():
    s = _settings(b2_freight_management_number="")
    assert s.b2_configured is False


def test_b2_configured_false_when_both_missing():
    s = _settings(b2_billing_customer_code="", b2_freight_management_number="")
    assert s.b2_configured is False


# ---------------------------------------------------------------------------
# CP932 変換失敗テスト
# ---------------------------------------------------------------------------

def _order_with_bad_address(address1: str) -> RentalOrder:
    """CP932 非対応文字を含む住所を持つ注文を生成するヘルパー."""
    return RentalOrder(
        order_id="rental-bad",
        order_number="#BAD-001",
        shipping_address=ShippingAddress(
            last_name="テスト",
            first_name="ユーザ",
            postal_code="100-0001",
            province="東京都",
            city="千代田区",
            address1=address1,
            phone="03-1234-5678",
        ),
        items=[OrderItem(title="スマートフォン", quantity=1)],
        package_size=PackageSize.COMPACT,
        delivery_date="20260501",
        delivery_time=DeliveryTimeSlot.NONE,
    )


def test_cp932_unencodable_raises_with_order_context(tmp_path: Path):
    """CP932 で表現できない文字 (例: emoji) を含む注文は ValueError を送出する."""
    order = _order_with_bad_address("千代田1-1🚀")  # rocket emoji — not in CP932
    settings = _settings(b2_output_dir=str(tmp_path))
    with pytest.raises(ValueError, match="CP932エンコード失敗"):
        append_b2_csv([order], settings)


def test_cp932_unencodable_error_includes_order_number(tmp_path: Path):
    """エラーメッセージに注文番号が含まれる."""
    order = _order_with_bad_address("千代田1-1\u2603")  # snowman — not in CP932
    settings = _settings(b2_output_dir=str(tmp_path))
    with pytest.raises(ValueError) as exc_info:
        append_b2_csv([order], settings)
    assert order.order_number in str(exc_info.value)


def test_cp932_valid_characters_do_not_raise(tmp_path: Path):
    """通常の日本語住所は CP932 変換でエラーにならない."""
    settings = _settings(b2_output_dir=str(tmp_path))
    append_b2_csv([_imakiire_order()], settings)  # should not raise
