from scripts.yamato_automation import (
    _extract_delivery_time_from_text,
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
