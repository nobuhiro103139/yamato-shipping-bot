import re
import unicodedata

from scripts.yamato_automation import (
    _extract_delivery_time_from_text,
    _normalize_recipient_phone,
    _parse_address_line_components,
)


def test_extract_delivery_time_from_confirmation_text_clock_format():
    assert _extract_delivery_time_from_text("お届け予定日時\n4/1 14:00～16:00") == "3"
    assert _extract_delivery_time_from_text("お届け予定日時\n4/1 8:00~12:00") == "1"


def test_extract_delivery_time_from_confirmation_text_japanese_format():
    assert _extract_delivery_time_from_text("配達希望時間帯: 午前中") == "1"
    assert _extract_delivery_time_from_text("配達希望時間帯: 19時～21時") == "7"


def test_parse_address_line_components_with_kanji_chome():
    parsed = _parse_address_line_components("一丁目1-19")
    assert parsed == {
        "chome": "1",
        "banchi": "1",
        "go": "19",
        "building": "",
    }


def test_parse_address_line_components_with_named_prefix_and_chome():
    parsed = _parse_address_line_components("北田宮3丁目6-59")
    assert parsed == {
        "chome": "3",
        "banchi": "6",
        "go": "59",
        "building": "",
    }


def test_parse_address_line_components_no_chome_numeric_only():
    """659-1 should NOT be treated as chome=659 — no 丁目 evidence."""
    parsed = _parse_address_line_components("津高659-1")
    assert parsed["chome"] == ""
    assert parsed["banchi"] == "659"
    assert parsed["go"] == "1"


def test_parse_address_line_components_bare_number():
    """Single number without hyphen should become banchi only."""
    parsed = _parse_address_line_components("津高42")
    assert parsed["chome"] == ""
    assert parsed["banchi"] == "42"
    assert parsed["go"] == ""


def test_parse_address_line_components_banchigo_separator():
    """#2125: 1丁目35番地6 — 番地 is banchi/go separator, not building name."""
    parsed = _parse_address_line_components("東本町1丁目35番地6")
    assert parsed["chome"] == "1"
    assert parsed["banchi"] == "35"
    assert parsed["go"] == "6"
    assert parsed["building"] == ""


# --- Phone normalization policy tests ---

def test_normalize_recipient_phone_japanese_intl():
    """Japanese +81 numbers should convert to domestic 0-prefix format."""
    assert _normalize_recipient_phone("+81-90-1234-5678") == "09012345678"
    assert _normalize_recipient_phone("+8190 1234 5678") == "09012345678"


def test_normalize_recipient_phone_domestic():
    """Domestic Japanese numbers pass through unchanged."""
    assert _normalize_recipient_phone("09012345678") == "09012345678"
    assert _normalize_recipient_phone("03-1234-5678") == "0312345678"


def test_normalize_recipient_phone_foreign_rejected():
    """Foreign numbers must return empty string — never coerce to domestic."""
    assert _normalize_recipient_phone("+821042977511") == ""
    assert _normalize_recipient_phone("+1-555-123-4567") == ""
    assert _normalize_recipient_phone("+44 20 7946 0958") == ""


def test_normalize_recipient_phone_empty():
    """Empty or whitespace input returns empty."""
    assert _normalize_recipient_phone("") == ""
    assert _normalize_recipient_phone("  ") == ""


# --- address2 fallback pattern tests ---
# These test the regex patterns used in _fill_recipient_info's address2 fallback
# to ensure correct extraction when address1 has town-name only (#1999 case).

def _simulate_addr2_chome_fallback(address2: str, chome_options: list[str]) -> dict:
    """Simulate the address2 fallback logic from _fill_recipient_info.

    Returns chome/banchi/go/building plus remaining_address2 — the value
    that should replace address2 after consuming the numeric portion.
    """
    addr2_normalized = unicodedata.normalize("NFKC", address2).strip()
    addr2_match = re.match(r"(\d+)-(\d+)(?:-(\d+))?\s*(.*)", addr2_normalized)
    if not addr2_match:
        return {"chome": "", "banchi": "", "go": "", "building": "", "remaining_address2": address2}
    candidate_chome = addr2_match.group(1)
    fullwidth_candidate = candidate_chome.translate(
        str.maketrans("0123456789", "０１２３４５６７８９")
    )
    candidate_text = f"{fullwidth_candidate}丁目"
    if any(candidate_text in opt for opt in chome_options):
        bld = addr2_match.group(4).strip()
        return {
            "chome": candidate_chome,
            "banchi": addr2_match.group(2),
            "go": addr2_match.group(3) or "",
            "building": bld,
            "remaining_address2": bld,
        }
    return {"chome": "", "banchi": "", "go": "", "building": "", "remaining_address2": address2}


def test_address2_fallback_chome_banchi_go():
    """#1999 case: address1='町名', address2='1-4-5 メゾンドジュネス101'"""
    opts = ["１丁目", "２丁目", "３丁目"]
    result = _simulate_addr2_chome_fallback("1-4-5 メゾンドジュネス101", opts)
    assert result["chome"] == "1"
    assert result["banchi"] == "4"
    assert result["go"] == "5"
    assert result["building"] == "メゾンドジュネス101"


def test_address2_fallback_no_go():
    """address2='2-15' — banchi only, no go."""
    opts = ["１丁目", "２丁目", "３丁目"]
    result = _simulate_addr2_chome_fallback("2-15", opts)
    assert result["chome"] == "2"
    assert result["banchi"] == "15"
    assert result["go"] == ""
    assert result["building"] == ""


def test_address2_fallback_building_only_rejected():
    """Building-only address2 like 'メゾンドジュネス101' must NOT be treated as chome."""
    opts = ["１丁目", "２丁目", "３丁目"]
    result = _simulate_addr2_chome_fallback("メゾンドジュネス101", opts)
    assert result["chome"] == ""
    assert result["banchi"] == ""


def test_address2_fallback_chome_not_in_popup():
    """address2='9-1-2' but popup only has 1-3丁目 — should not match."""
    opts = ["１丁目", "２丁目", "３丁目"]
    result = _simulate_addr2_chome_fallback("9-1-2", opts)
    assert result["chome"] == ""


def test_address2_fallback_fullwidth_input():
    """Full-width digits in address2 should be normalized and matched."""
    opts = ["１丁目", "２丁目", "３丁目"]
    result = _simulate_addr2_chome_fallback("１-４-５ 建物名", opts)
    assert result["chome"] == "1"
    assert result["banchi"] == "4"
    assert result["go"] == "5"
    assert result["building"] == "建物名"


# --- address2 fallback duplication prevention tests ---

def test_address2_fallback_numeric_only_no_duplication():
    """#1999 regression: address2='5-2-10' consumed as chome/banchi/go.

    remaining_address2 must be '' so it does NOT leak into address4.
    """
    opts = ["５丁目", "６丁目"]
    result = _simulate_addr2_chome_fallback("5-2-10", opts)
    assert result["chome"] == "5"
    assert result["banchi"] == "2"
    assert result["go"] == "10"
    assert result["remaining_address2"] == ""


def test_address2_fallback_with_building_preserves_building():
    """address2='1-4-5 メゾンドジュネス101' — building must survive in remaining_address2."""
    opts = ["１丁目", "２丁目"]
    result = _simulate_addr2_chome_fallback("1-4-5 メゾンドジュネス101", opts)
    assert result["remaining_address2"] == "メゾンドジュネス101"


def test_address2_fallback_no_match_preserves_address2():
    """When chome is not in popup, address2 must remain unchanged."""
    opts = ["１丁目", "２丁目"]
    result = _simulate_addr2_chome_fallback("9-1-2", opts)
    assert result["remaining_address2"] == "9-1-2"


def test_address2_fallback_building_only_preserves_address2():
    """Non-numeric address2 like 'メゾン201' should be untouched."""
    opts = ["１丁目", "２丁目"]
    result = _simulate_addr2_chome_fallback("メゾン201", opts)
    assert result["remaining_address2"] == "メゾン201"


# --- Postal mismatch diagnostics ---

def _simulate_recipient_validation_error(address1_snapshot: str, postal_code: str) -> str:
    """Simulate the error message raised when next button stays disabled.

    Mirrors the branching added in _fill_recipient_info to detect postal mismatch.
    Returns the RuntimeError message that would be raised.
    """
    if not address1_snapshot or address1_snapshot == "(not found)":
        return (
            f"Recipient step validation failed: prefecture/city (address1) is empty after "
            f"postal lookup — postal code mismatch likely "
            f"(postal={postal_code!r}). "
            "Verify the postal code is correct and retry."
        )
    return "Recipient step validation failed; next button is still disabled"


def test_postal_mismatch_error_when_address1_empty():
    """Empty address1 after postal lookup must yield postal-mismatch hint."""
    msg = _simulate_recipient_validation_error("", "489-4816")
    assert "postal code mismatch likely" in msg
    assert "489-4816" in msg


def test_postal_mismatch_error_when_address1_not_found():
    """'(not found)' address1 (field absent from DOM) triggers mismatch hint."""
    msg = _simulate_recipient_validation_error("(not found)", "000-0000")
    assert "postal code mismatch likely" in msg


def test_no_postal_mismatch_hint_when_address1_filled():
    """When address1 is populated, raise the generic disabled-button error."""
    msg = _simulate_recipient_validation_error("愛知県みよし市", "470-0200")
    assert "postal code mismatch" not in msg
    assert "next button is still disabled" in msg
