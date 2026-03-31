import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from scripts.config import Settings, get_settings
from scripts.models import (
    PackageSize,
    RentalOrder,
    ShippingResult,
    ShippingStatus,
    VerificationReport,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from playwright.async_api import Dialog, Page

QR_CODE_DIR = Path("qr_codes")
QR_CODE_DIR.mkdir(exist_ok=True)

VERIFICATION_DIR = Path("verification_logs")
VERIFICATION_DIR.mkdir(exist_ok=True)

YAMATO_SEND_URL = "https://sp-send.kuronekoyamato.co.jp/"

TIMEOUT_PAGE_LOAD_MS = 3000
TIMEOUT_NAVIGATION_MS = 3000
TIMEOUT_POSTAL_LOOKUP_MS = 3000
TIMEOUT_INPUT_MS = 500
TIMEOUT_DROPDOWN_UPDATE_MS = 2000
TIMEOUT_DIALOG_MS = 3000
TIMEOUT_LOGIN_POLL_MS = 2000
TIMEOUT_LOGIN_MAX_S = 60
SLOW_MO_MS = 500
PRODUCT_NAME_MAX_LENGTH = 17


def _safe_url(url: str) -> str:
    """Strip query/fragment from URL to avoid logging auth tokens."""
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}{u.path}"


DEVICE_CONFIG: dict[str, object] = {
    "user_agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.6 Mobile/15E148 Safari/604.1"
    ),
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
}

PACKAGE_SIZE_TO_RADIO_VALUE: dict[PackageSize, str] = {
    PackageSize.COMPACT: "C",
    PackageSize.S: "S",
    PackageSize.M: "M",
    PackageSize.L: "L",
    PackageSize.LL: "LL",
}

# 配達時間帯の表示名 → select value のマッピング
# 確認ページではテキスト表示されるため、テキストから逆引きする
TIME_SLOT_DISPLAY_TO_VALUE: dict[str, str] = {
    "午前中": "1",
    "8:00~12:00": "1",
    "8:00～12:00": "1",
    "14時~16時": "3",
    "14時～16時": "3",
    "14:00~16:00": "3",
    "14:00～16:00": "3",
    "16時~18時": "4",
    "16時～18時": "4",
    "16:00~18:00": "4",
    "16:00～18:00": "4",
    "18時~20時": "5",
    "18時～20時": "5",
    "18:00~20:00": "5",
    "18:00～20:00": "5",
    "19時~21時": "7",
    "19時～21時": "7",
    "19:00~21:00": "7",
    "19:00～21:00": "7",
}

PACKAGE_COUNT_IDS: dict[int, str] = {
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
}

YAMATO_SELECTORS = {
    "prepay_btn": "a#nextLeavePay",
    "item_name": 'input[name="viwb2050ActionBean.itemName"]',
    "size_radio": 'input[name="viwb2050ActionBean.size"]',
    "handling_checkbox": 'input[name="handling"]',
    "not_prohibited": 'input[name="viwb2050ActionBean.notProhibited"]',
    "recipient_last_name": 'input[name="viwb3040ActionBean.lastName"]',
    "recipient_first_name": 'input[name="viwb3040ActionBean.firstName"]',
    "recipient_zip": 'input[name="viwb3040ActionBean.zipCode"]',
    "address_search_btn": "button#btnSearch",
    "recipient_address3": 'input[name="viwb3040ActionBean.address3"]',
    "recipient_address3opt": 'input[name="viwb3040ActionBean.address3opt"]',
    "recipient_address4": 'input[name="viwb3040ActionBean.address4"]',
    "recipient_phone": 'input[name="viwb3040ActionBean.phoneNumber"]',
    "next_btn": "a#next",
    "sender_last_name": 'input[name="viwb3130ActionBean.lastName"]',
    "sender_first_name": 'input[name="viwb3130ActionBean.firstName"]',
    "sender_zip": 'input[name="viwb3130ActionBean.zipCode"]',
    "sender_address3": 'input[name="viwb3130ActionBean.address3"]',
    "sender_address3opt": 'input[name="viwb3130ActionBean.address3opt"]',
    "sender_address4": 'input[name="viwb3130ActionBean.address4"]',
    "sender_phone": 'input[name="viwb3130ActionBean.phoneNumber"]',
    "shipping_date": 'select[name="viwb4100ActionBean.dateToShip"]',
    "delivery_date": 'select[name="viwb4100ActionBean.dateToReceive"]',
    "delivery_time": 'select[name="viwb4100ActionBean.timeToReceive"]',
    "login_form_id": "#login-form-id",
    "login_form_password": "#login-form-password",
    "login_form_submit": "#login-form-submit",
}


def _extract_delivery_time_from_text(page_text: str) -> str:
    normalized_text = unicodedata.normalize("NFKC", page_text or "")
    for display_name, val in TIME_SLOT_DISPLAY_TO_VALUE.items():
        norm_display = unicodedata.normalize("NFKC", display_name)
        if norm_display in normalized_text or display_name in page_text:
            return val
    return ""


def _parse_kanji_number(token: str) -> int | None:
    token = token.strip()
    if not token:
        return None

    if token.isdigit():
        return int(token)

    digit_map = {
        "〇": 0,
        "零": 0,
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    unit_map = {"十": 10, "百": 100}

    total = 0
    current = 0
    for ch in token:
        if ch in digit_map:
            current = digit_map[ch]
            continue
        if ch in unit_map:
            unit = unit_map[ch]
            total += (current or 1) * unit
            current = 0
            continue
        return None

    return total + current


def _normalize_chome_token(token: str) -> str:
    normalized = unicodedata.normalize("NFKC", token or "").strip()
    if not normalized:
        return ""
    if normalized.isdigit():
        return normalized
    parsed = _parse_kanji_number(normalized)
    return str(parsed) if parsed is not None else ""


def _parse_address_line_components(address1: str) -> dict[str, str]:
    parsed = {
        "chome": "",
        "banchi": "",
        "go": "",
        "building": "",
    }
    normalized = unicodedata.normalize("NFKC", address1 or "").strip()
    if not normalized:
        return parsed

    match = re.search(
        r"(?P<chome>[0-9一二三四五六七八九十百〇零]+)丁目(?P<rest>.*)$",
        normalized,
    )
    if match:
        parsed["chome"] = _normalize_chome_token(match.group("chome"))
        rest = match.group("rest").strip()
    else:
        rest_match = re.search(
            r"(?P<chome>\d+)-(?P<banchi>\d+)(?:-(?P<go>\d+))?(?P<tail>.*)$",
            normalized,
        )
        if rest_match:
            parsed["chome"] = rest_match.group("chome")
            parsed["banchi"] = rest_match.group("banchi")
            parsed["go"] = rest_match.group("go") or ""
            parsed["building"] = rest_match.group("tail").strip()
        return parsed

    rest = rest.lstrip("-")
    rest_match = re.match(
        r"(?P<banchi>\d+)(?:-(?P<go>\d+))?(?P<tail>.*)$",
        rest,
    )
    if rest_match:
        parsed["banchi"] = rest_match.group("banchi")
        parsed["go"] = rest_match.group("go") or ""
        parsed["building"] = rest_match.group("tail").strip()

    return parsed


async def _get_page_markers(page: "Page") -> dict[str, bool]:
    recipient_inputs = page.locator(
        YAMATO_SELECTORS["recipient_last_name"]
    )
    sender_inputs = page.locator(
        YAMATO_SELECTORS["sender_last_name"]
    )
    shipping_date_select = page.locator(
        YAMATO_SELECTORS["shipping_date"]
    )
    save_return = page.locator("a#saveReturn")
    do_payment_forward = page.locator("a#doPaymentForward")

    return {
        "recipient_inputs": await recipient_inputs.count() > 0,
        "sender_inputs": await sender_inputs.count() > 0,
        "shipping_date_select": await shipping_date_select.count() > 0,
        "save_return": await save_return.count() > 0,
        "payment_forward": await do_payment_forward.count() > 0,
    }


async def _assert_recipient_step_advanced(page: "Page") -> None:
    markers = await _get_page_markers(page)
    if not markers["recipient_inputs"]:
        return

    # Capture form field values for diagnosis
    field_snapshot = await page.evaluate("""() => {
        const fields = {};
        const selectors = {
            lastName: 'input[name="viwb3040ActionBean.lastName"]',
            firstName: 'input[name="viwb3040ActionBean.firstName"]',
            zipCode: 'input[name="viwb3040ActionBean.zipCode"]',
            address1: 'input[name="viwb3040ActionBean.address1"]',
            address2: 'input[name="viwb3040ActionBean.address2"]',
            address3: 'input[name="viwb3040ActionBean.address3"]',
            address3opt: 'input[name="viwb3040ActionBean.address3opt"]',
            address4: 'input[name="viwb3040ActionBean.address4"]',
            phoneNumber: 'input[name="viwb3040ActionBean.phoneNumber"]',
        };
        for (const [name, sel] of Object.entries(selectors)) {
            const el = document.querySelector(sel);
            fields[name] = el ? el.value : '(not found)';
        }
        return fields;
    }""")
    empty_fields = [k for k, v in field_snapshot.items() if v in ('', '(not found)')]

    page_text = await page.evaluate(
        "() => (document.body && document.body.innerText) || ''"
    )
    error_lines = [
        line.strip()
        for line in page_text.splitlines()
        if any(token in line for token in ("正しく", "エラー", "入力してください"))
        and "入力した情報" not in line
    ]
    error_preview = " | ".join(error_lines[:5])
    raise RuntimeError(
        "Recipient step did not advance; still on recipient input page"
        + (f"; empty_fields={empty_fields}" if empty_fields else "")
        + (f"; errors=[{error_preview}]" if error_preview else "")
        + f"; field_snapshot={json.dumps(field_snapshot, ensure_ascii=False)}"
    )


async def _assert_confirmation_page(page: "Page", context: str) -> None:
    markers = await _get_page_markers(page)
    if markers["save_return"] or markers["payment_forward"]:
        if markers["recipient_inputs"]:
            raise RuntimeError(
                f"{context}: confirmation/save controls are visible but recipient input page is still active"
            )
        return

    page_title = await page.evaluate("() => document.title || ''")
    raise RuntimeError(
        f"{context}: not on confirmation page "
        f"(url={_safe_url(page.url)}, title={page_title!r}, markers={markers})"
    )


async def process_shipment(order: RentalOrder) -> ShippingResult:
    settings = get_settings()

    if not settings.kuroneko_configured:
        return ShippingResult(
            order_id=order.order_id,
            order_number=order.order_number,
            status=ShippingStatus.FAILED,
            error_message="Kuroneko credentials not configured.",
        )

    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        return ShippingResult(
            order_id=order.order_id,
            order_number=order.order_number,
            status=ShippingStatus.FAILED,
            error_message="Playwright is not installed.",
        )

    try:
        result = await _run_yamato_automation(order, settings)
        return result
    except Exception as e:
        return ShippingResult(
            order_id=order.order_id,
            order_number=order.order_number,
            status=ShippingStatus.FAILED,
            error_message=str(e),
        )


async def _run_yamato_automation(
    order: RentalOrder, settings: Settings
) -> ShippingResult:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=settings.headless_browser,
            slow_mo=SLOW_MO_MS,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(**DEVICE_CONFIG)
        page = await context.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => false });"
        )

        async def _handle_dialog(dialog: "Dialog") -> None:
            logger.info("Dialog [%s]: %s", dialog.type, dialog.message)
            await dialog.accept()

        page.on("dialog", _handle_dialog)

        try:
            await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(TIMEOUT_PAGE_LOAD_MS)

            await _login(page, settings)
            logger.info("STEP: login done, URL=%s", _safe_url(page.url))

            await _navigate_to_package_settings(page, order)
            logger.info("STEP: navigate_to_package_settings done, URL=%s", _safe_url(page.url))

            await _fill_package_settings(page, order)
            logger.info("STEP: fill_package_settings done")

            await _select_direct_address_input(page)
            logger.info("STEP: select_direct_address_input done")

            await _fill_recipient_info(page, order)
            logger.info("STEP: fill_recipient_info done")

            await _select_sender_from_address_book(page, settings)
            await _confirm_sender_info(page)
            logger.info("STEP: sender done")

            await _select_shipping_location(page, settings)
            logger.info("STEP: shipping_location done")

            await _fill_delivery_datetime(page, order)
            logger.info("STEP: delivery_datetime done")

            # === 検証フェーズ: 設定内容の確認ページで確定値をテキストから取得 ===
            # このページ (設定内容の確認) にはフォーム要素 (select/input) が
            # 存在しないが、配達日時・メールなどの確定値がテキスト表示されている。
            # テキストベースのフォールバックで正しく抽出する。
            await _assert_confirmation_page(page, "Verification")
            verification = await _verify_confirmation(page, order, settings)
            _log_verification_summary(verification)
            verification_path = _save_verification_report(verification)
            logger.info("STEP: verification done (%s)", verification_path)

            # 保存前スクリーンショット（確認画面の状態を記録）
            pre_save_screenshot = str(
                QR_CODE_DIR / f"{order.order_number}_pre_save.png"
            )
            await page.screenshot(path=pre_save_screenshot, full_page=True)

            await _assert_confirmation_page(page, "Save draft")
            await _save_draft(page)
            logger.info("STEP: save_draft done")

            screenshot_path = str(QR_CODE_DIR / f"{order.order_number}_confirmation.png")
            await page.screenshot(path=screenshot_path, full_page=True)

            return ShippingResult(
                order_id=order.order_id,
                order_number=order.order_number,
                status=ShippingStatus.COMPLETED,
                qr_code_path=screenshot_path,
                verification=verification,
            )

        except Exception:
            error_screenshot = str(QR_CODE_DIR / f"{order.order_number}_error.png")
            await page.screenshot(path=error_screenshot, full_page=True)
            raise

        finally:
            await browser.close()


async def _login(page: "Page", settings: Settings) -> None:
    content = await page.content()
    if "ログインして利用する" not in content:
        logout_loc = page.locator("text=ログアウト")
        if await logout_loc.count() > 0 and await logout_loc.first.is_visible():
            logger.info("Already logged in")
            return

    login_btn = page.get_by_text("ログインして利用する", exact=False)
    if await login_btn.count() > 0:
        await login_btn.first.click()
        await page.wait_for_timeout(5000)

    is_login_page = "auth.kms" in page.url or "id.kuronekoyamato.co.jp" in page.url
    if not is_login_page:
        logger.warning("Expected login page, got: %s", _safe_url(page.url))
        logout_loc = page.locator("text=ログアウト")
        if await logout_loc.count() > 0 and await logout_loc.first.is_visible():
            logger.info("Already logged in (via unexpected flow)")
            return
        raise RuntimeError(f"Login flow failed: unexpected URL {page.url}")

    await page.locator(YAMATO_SELECTORS["login_form_id"]).fill(
        settings.kuroneko_login_id
    )
    await page.locator(YAMATO_SELECTORS["login_form_password"]).fill(
        settings.kuroneko_password
    )
    await page.locator(YAMATO_SELECTORS["login_form_submit"]).click()

    max_polls = TIMEOUT_LOGIN_MAX_S * 1000 // TIMEOUT_LOGIN_POLL_MS
    for i in range(max_polls):
        await page.wait_for_timeout(TIMEOUT_LOGIN_POLL_MS)
        url = page.url
        if "sp-send" in url:
            logger.info(
                "Login redirect to sp-send after %ds",
                (i + 1) * TIMEOUT_LOGIN_POLL_MS // 1000,
            )
            break
        elif "member" in url:
            logger.info("Redirected to member page, navigating to sp-send")
            await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(TIMEOUT_PAGE_LOAD_MS)
            break
    else:
        logger.warning("Login redirect timeout after %ds", TIMEOUT_LOGIN_MAX_S)
        await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(TIMEOUT_PAGE_LOAD_MS)

    content = await page.content()
    logout_loc = page.locator("text=ログアウト")
    is_logged_in = (
        await logout_loc.count() > 0 and await logout_loc.first.is_visible()
    )
    still_has_login = "ログインして利用する" in content

    if still_has_login and not is_logged_in:
        logger.info("SSO retry: clicking login button again")
        sso_btn = page.get_by_text("ログインして利用する", exact=False)
        if await sso_btn.count() > 0:
            await sso_btn.first.click()
            await page.wait_for_timeout(8000)
            if "auth.kms" in page.url or "id.kuronekoyamato.co.jp" in page.url:
                for _ in range(15):
                    await page.wait_for_timeout(TIMEOUT_LOGIN_POLL_MS)
                    if "sp-send" in page.url:
                        break
                else:
                    await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded")
                    await page.wait_for_timeout(TIMEOUT_PAGE_LOAD_MS)

    logout_loc = page.locator("text=ログアウト")
    is_logged_in = (
        await logout_loc.count() > 0 and await logout_loc.first.is_visible()
    )
    if not is_logged_in:
        raise RuntimeError("Login failed: could not establish session on sp-send")


async def _navigate_to_package_settings(page: "Page", order: RentalOrder) -> None:
    normal = page.get_by_role("link", name="通常の荷物を送る")
    if await normal.count() > 0:
        await normal.first.click()
    else:
        await page.get_by_text("通常の荷物を送る").first.click()
    await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    await _check_session_error(page)

    prepay = page.locator(YAMATO_SELECTORS["prepay_btn"])
    if await prepay.count() > 0:
        await prepay.click()
    else:
        img = page.get_by_alt_text("発払いで荷物を送る")
        if await img.count() > 0:
            await img.first.click()
        else:
            raise RuntimeError("発払い button not found")
    await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    await _check_session_error(page)

    total_items = sum(item.quantity for item in order.items)
    count = min(total_items, 5)
    count_id = PACKAGE_COUNT_IDS.get(count, "one")
    count_btn = page.locator(f"a#{count_id}")
    if await count_btn.count() > 0:
        await count_btn.click()
    else:
        raise RuntimeError(f"Package count button a#{count_id} not found")
    await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    await _check_session_error(page)


async def _dismiss_modal(page: "Page") -> None:
    """モーダルオーバーレイ (modal3 等) が表示されていれば閉じる."""
    for selector in [
        "#modal3 a",           # modal3 内のリンク (OK / 閉じる)
        "#modal3 button",      # modal3 内のボタン
        ".modal-overlay + div a",
        'a:has-text("OK")',
        'button:has-text("OK")',
        'a:has-text("閉じる")',
        'button:has-text("閉じる")',
    ]:
        try:
            loc = page.locator(selector)
            if await loc.count() > 0 and await loc.first.is_visible():
                await loc.first.click()
                await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                logger.info("Dismissed modal via: %s", selector)
                return
        except Exception:
            continue

    # JS フォールバック: モーダルオーバーレイを非表示にする
    modal_visible = await page.evaluate("""() => {
        const overlay = document.querySelector('.modal-overlay');
        return overlay && overlay.offsetParent !== null;
    }""")
    if modal_visible:
        await page.evaluate("""() => {
            document.querySelectorAll('.modal-overlay').forEach(el => {
                el.style.display = 'none';
            });
            document.querySelectorAll('[id^="modal"]').forEach(el => {
                el.style.display = 'none';
            });
        }""")
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)
        logger.info("Dismissed modal via JS (forced hide)")


async def _fill_package_settings(page: "Page", order: RentalOrder) -> None:
    radio_value = PACKAGE_SIZE_TO_RADIO_VALUE.get(order.package_size, "C")
    logger.info("Selecting package size: %s (radio value=%s)", order.package_size, radio_value)

    # --- 宅急便コンパクト選択: ラベルテキストを直接クリック ---
    # JS evaluate だけでは UI フレームワークのイベントが発火しないため、
    # Playwright ネイティブの click でラベルを操作する
    size_selected = False

    if radio_value == "C":
        # 方法1: 「宅急便コンパクト」ラベルテキストを直接クリック
        compact_label = page.get_by_text("宅急便コンパクト", exact=False)
        if await compact_label.count() > 0:
            await compact_label.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Clicked label text '宅急便コンパクト'")
            size_selected = True

            # 宅急便コンパクト選択後にモーダル (modal3 等) が出ることがある
            # → OK / 閉じるボタンをクリックしてモーダルを閉じる
            await _dismiss_modal(page)

    if not size_selected:
        # 方法2: radio input の親 label を Playwright でクリック
        radio = page.locator(
            f'input[name="viwb2050ActionBean.size"][value="{radio_value}"]'
        )
        if await radio.count() > 0:
            parent_label = radio.locator("xpath=ancestor::label")
            if await parent_label.count() > 0:
                await parent_label.first.click()
                logger.info("Clicked parent label for radio value=%s", radio_value)
                size_selected = True
            else:
                await radio.first.click(force=True)
                logger.info("Force-clicked radio value=%s", radio_value)
                size_selected = True
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    if not size_selected:
        # 方法3: JS evaluate フォールバック (最終手段)
        await page.evaluate(
            """(targetValue) => {
                const radios = document.querySelectorAll('input[name="viwb2050ActionBean.size"]');
                for (const r of radios) {
                    if (r.value === targetValue) {
                        r.checked = true;
                        r.dispatchEvent(new Event('change', {bubbles: true}));
                        r.dispatchEvent(new Event('click', {bubbles: true}));
                        const lbl = r.closest('label');
                        if (lbl) lbl.click();
                        return;
                    }
                }
            }""",
            radio_value,
        )
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)
        logger.info("JS evaluate fallback for radio value=%s", radio_value)

    # 選択結果を検証ログ
    checked_value = await page.evaluate("""() => {
        const checked = document.querySelector('input[name="viwb2050ActionBean.size"]:checked');
        return checked ? checked.value : null;
    }""")
    logger.info("Size radio checked value after selection: %s (expected %s)", checked_value, radio_value)

    # 品名は固定で「スマートフォン」
    item_name_input = page.locator(YAMATO_SELECTORS["item_name"])
    if await item_name_input.count() > 0:
        await item_name_input.first.fill("スマートフォン")
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    # 精密機械チェック - ラベルを直接クリック (compact UI にない場合はスキップ)
    try:
        handling_cb = page.locator('input[name="handling"][value="01"]')
        if await handling_cb.count() > 0 and not await handling_cb.first.is_checked():
            # label クリックが modal に遮られる場合は force=True で直接チェック
            handling_label = page.get_by_text("精密機械", exact=False)
            if await handling_label.count() > 0:
                try:
                    await handling_label.first.click(timeout=3000)
                    logger.info("Clicked 精密機械 label")
                except Exception:
                    await handling_cb.first.click(force=True)
                    logger.info("Force-clicked 精密機械 checkbox")
    except Exception:
        logger.info("精密機械 checkbox not found (may not exist for compact)")
    await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    # 宅急便で送れないものに該当しません チェック
    # 宅急便コンパクトの場合は「宅急便コンパクトで送れないもの」表記の可能性あり
    try:
        prohibited_cb = page.locator('input[name="viwb2050ActionBean.notProhibited"]')
        if await prohibited_cb.count() > 0 and not await prohibited_cb.first.is_checked():
            clicked = False
            for prohibited_text in [
                "送れないものに該当しません",
                "宅急便で送れないものに該当しません",
                "宅急便コンパクトで送れないものに該当しません",
            ]:
                prohibited_label = page.get_by_text(prohibited_text, exact=False)
                if await prohibited_label.count() > 0:
                    try:
                        await prohibited_label.first.click(timeout=3000)
                        logger.info("Clicked prohibited checkbox via text: %s", prohibited_text)
                        clicked = True
                    except Exception:
                        continue
                    break
            if not clicked:
                await prohibited_cb.first.click(force=True)
                logger.info("Force-clicked prohibited checkbox")
    except Exception:
        logger.info("Prohibited checkbox not found (may not exist for compact)")
    await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    next_clicked = False
    for sel in [
        'a[data-action="Viwb2050Action_doNext.action"]',
        'a[onclick*="Viwb2050Action_doNext"]',
        "a#next",
    ]:
        loc = page.locator(sel)
        if await loc.count() > 0:
            await loc.first.click(force=True)
            logger.debug("Package settings next clicked via: %s", sel)
            next_clicked = True
            break

    if not next_clicked:
        for txt in ["荷物内容を入力してください", "次へ", "次へ進む"]:
            btn = page.get_by_text(txt, exact=False)
            if await btn.count() > 0:
                await btn.first.click()
                logger.debug("Package settings next clicked via text: %s", txt)
                next_clicked = True
                break

    if not next_clicked:
        await page.evaluate("""() => {
            const links = document.querySelectorAll('a[onclick*="doNext"], a[onclick*="setAction"]');
            for (const a of links) {
                if (a.offsetParent !== null) { a.click(); return; }
            }
        }""")

    await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    await page.wait_for_timeout(TIMEOUT_DIALOG_MS)

    # 航空危険物の確認モーダルが出た場合「OK」をクリック
    ok_btn = page.get_by_text("OK", exact=True)
    if await ok_btn.count() > 0 and await ok_btn.last.is_visible():
        await ok_btn.last.click()
        logger.info("Dismissed aviation warning modal")
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)


async def _select_direct_address_input(page: "Page") -> None:
    direct = page.get_by_text("直接住所を入力する", exact=False)
    if await direct.count() > 0:
        await direct.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)


async def _fill_recipient_info(page: "Page", order: RentalOrder) -> None:
    addr = order.shipping_address
    logger.info(
        "Recipient addr: last=%s, first=%s, postal=%s, addr1=%s, addr2=%s, building=%s, chome=%s, banchi=%s, go=%s",
        addr.last_name, addr.first_name, addr.postal_code,
        addr.address1, addr.address2, addr.building,
        addr.chome, addr.banchi, addr.go,
    )

    # Shopify shippingAddress: lastName=姓, firstName=名 — そのまま入力
    await _fill_input(page, YAMATO_SELECTORS["recipient_last_name"], addr.last_name)
    if addr.first_name:
        await _fill_input(page, YAMATO_SELECTORS["recipient_first_name"], addr.first_name)

    postal_code = addr.postal_code.replace("-", "")
    await _fill_input(page, YAMATO_SELECTORS["recipient_zip"], postal_code)

    search_btn = page.locator(YAMATO_SELECTORS["address_search_btn"])
    if await search_btn.count() > 0:
        await search_btn.first.click()
        await page.wait_for_timeout(5000)  # ポップアップ表示を十分待つ

    # 住所選択ポップアップの処理 (丁目 or 字・町名)
    chome_to_select = addr.chome
    banchi_value = addr.banchi
    go_value = addr.go
    address_for_field = addr.address1
    selected_popup_text = ""
    parsed_address1 = _parse_address_line_components(addr.address1)

    if parsed_address1["chome"] and not chome_to_select:
        chome_to_select = parsed_address1["chome"]
    if parsed_address1["banchi"] and not banchi_value:
        banchi_value = parsed_address1["banchi"]
    if parsed_address1["go"] and not go_value:
        go_value = parsed_address1["go"]
    if parsed_address1["chome"] and parsed_address1["banchi"]:
        address_for_field = ""
        if parsed_address1["building"] and not addr.building:
            addr = addr.model_copy(update={"building": parsed_address1["building"]})
    logger.info(
        "Parsed address1 components: chome=%s, banchi=%s, go=%s, building=%s",
        parsed_address1["chome"], parsed_address1["banchi"],
        parsed_address1["go"], parsed_address1["building"],
    )

    # Step 1: Detect any address-selection popup in iframe
    # Yamato shows either numbered 丁目 options OR named 字/町 sections
    popup_frame = None
    all_popup_options: list[str] = []
    chome_options: list[str] = []  # subset: options containing 丁目
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            frame_text = await frame.locator("body").inner_text(timeout=2000)
            if "選択してください" in frame_text or "丁目" in frame_text:
                popup_frame = frame
                all_popup_options = await frame.evaluate("""() => {
                    const links = document.querySelectorAll('a');
                    return Array.from(links)
                        .map(a => a.textContent.trim())
                        .filter(t => t.length > 0);
                }""")
                chome_options = [o for o in all_popup_options if "丁目" in o]
                logger.info(
                    "Address popup found: %d options total, %d chome. Options: %s",
                    len(all_popup_options), len(chome_options), all_popup_options,
                )
                break
        except Exception:
            continue

    has_popup = popup_frame is not None and len(all_popup_options) > 0
    has_chome_options = len(chome_options) > 0

    # Step 2: Determine what to click and how to fill remaining fields
    popup_clicked = False

    if has_popup and has_chome_options:
        # Numbered 丁目 popup — parse address1 for chome-banchi-go
        # パターン例: "白金台1-4-5 メゾンドジュネス101", "1-2-3", "白金台1丁目4-5"
        if not chome_to_select and addr.address1:
            # 先に建物名を分離 (スペース区切りで後半を building 候補)
            addr1_parts = addr.address1.strip().split(None, 1)
            addr1_main = addr.address1
            addr1_building = ""
            # "1-4-5 メゾンドジュネス101" → 数字部分とbuilding
            for i, part in enumerate(addr1_parts):
                if re.search(r"\d+-\d+", part):
                    addr1_main = part
                    addr1_building = " ".join(addr1_parts[i + 1:]) if i + 1 < len(addr1_parts) else ""
                    break

            match = re.search(r"(\d+)-(\d+)(?:-(\d+))?", addr1_main)
            if match:
                candidate_chome = match.group(1)
                fullwidth_candidate = candidate_chome.translate(
                    str.maketrans("0123456789", "０１２３４５６７８９")
                )
                candidate_text = f"{fullwidth_candidate}丁目"
                if any(candidate_text in opt for opt in chome_options):
                    chome_to_select = candidate_chome
                    banchi_value = match.group(2)
                    go_value = match.group(3) or ""
                    address_for_field = ""
                    # 建物名を building として保存 (既存の building が空の場合)
                    if addr1_building and not addr.building:
                        addr = addr.model_copy(update={"building": addr1_building})
                    logger.info(
                        "Parsed chome=%s, banchi=%s, go=%s, building=%s (confirmed in popup)",
                        chome_to_select, banchi_value, go_value, addr1_building,
                    )
                else:
                    logger.info(
                        "Trailing '%s' not in chome options; treating as raw address",
                        candidate_chome,
                    )

        if chome_to_select:
            fullwidth_chome = chome_to_select.translate(
                str.maketrans("0123456789", "０１２３４５６７８９")
            )
            for txt in [f"{fullwidth_chome}丁目", f"{chome_to_select}丁目"]:
                for loc in [
                    popup_frame.get_by_text(txt, exact=True),
                    popup_frame.get_by_role("link", name=txt),
                    popup_frame.locator(f"a:has-text('{txt}')"),
                ]:
                    try:
                        if await loc.count() > 0:
                            await loc.first.click()
                            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                            logger.info("Selected chome: %s", txt)
                            popup_clicked = True
                            selected_popup_text = txt
                            break
                    except Exception:
                        continue
                if popup_clicked:
                    break
            if not popup_clicked:
                logger.warning("Could not click chome: %s", chome_to_select)

    elif has_popup and not has_chome_options:
        # Named 字/町 section popup (e.g., 中荒古, 大通, etc.)
        # Try to match address1 against the options
        if addr.address1:
            matched_option = None
            remaining_address = addr.address1

            # Try each popup option as a prefix/substring of address1
            # Sort by length descending to prefer longest match
            sorted_options = sorted(all_popup_options, key=len, reverse=True)
            for opt in sorted_options:
                if opt in addr.address1:
                    matched_option = opt
                    # Extract the part after the matched option
                    idx = addr.address1.index(opt) + len(opt)
                    remaining_address = addr.address1[idx:]
                    break

            if matched_option:
                logger.info(
                    "Matched address section '%s' in popup; remaining='%s'",
                    matched_option, remaining_address,
                )
                loc = popup_frame.get_by_text(matched_option, exact=True)
                if await loc.count() > 0:
                    await loc.first.click()
                    await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                    popup_clicked = True
                    selected_popup_text = matched_option
                    logger.info("Clicked section: %s", matched_option)

                    # Parse remaining for banchi-go
                    # e.g., "30-12" -> banchi=30, go=12
                    # e.g., "6丁目28-20" -> banchi=28, go=20 (丁目部分は住所選択済み)
                    cleaned_remaining = re.sub(r"^\d+丁目", "", remaining_address.lstrip("-"))
                    remaining_match = re.match(r"(\d+)(?:-(\d+))?$", cleaned_remaining.lstrip("-"))
                    if remaining_match and not banchi_value:
                        banchi_value = remaining_match.group(1)
                        go_value = remaining_match.group(2) or ""
                        address_for_field = ""
                        logger.info(
                            "Parsed remaining: banchi=%s, go=%s",
                            banchi_value, go_value,
                        )
                    elif remaining_address.strip():
                        address_for_field = remaining_address.lstrip("-").strip()
                    else:
                        address_for_field = ""
                else:
                    logger.warning("Option '%s' found in text but not clickable", matched_option)

            if not popup_clicked:
                logger.warning(
                    "Could not match address1 '%s' to any popup option %s",
                    addr.address1, all_popup_options,
                )

    # Step 3: Don't corrupt the address by clicking an arbitrary fallback option.
    if has_popup and not popup_clicked:
        raise RuntimeError(
            "Address popup appeared but no matching option could be selected; "
            f"address1={addr.address1!r}, options={all_popup_options}"
        )

    if not has_popup and addr.address1:
        logger.info("No address popup after postal lookup; using raw address1: %s", addr.address1)

    # Step 3.5: 都道府県・市区郡町村が空の場合、郵便番号検索を再実行して埋める
    address1_val = await page.evaluate(
        "() => (document.querySelector('input[name$=\"address1\"]') || {}).value || ''"
    )
    if not address1_val:
        logger.info("Prefecture/city empty after popup; re-triggering postal lookup")
        search_btn = page.locator(YAMATO_SELECTORS["address_search_btn"])
        if await search_btn.count() > 0:
            await _scroll_and_click(page, search_btn.first)
            await page.wait_for_timeout(5000)

            # 再度ポップアップが出た場合は同じ選択をする
            for frame in page.frames:
                if frame == page.main_frame:
                    continue
                try:
                    frame_text = await frame.locator("body").inner_text(timeout=2000)
                    if "選択してください" in frame_text or "丁目" in frame_text:
                        # 前回と同じ選択肢をクリック
                        if popup_clicked and has_popup and selected_popup_text:
                            for loc in [
                                frame.get_by_text(selected_popup_text, exact=True),
                                frame.get_by_role("link", name=selected_popup_text),
                                frame.locator(f"a:has-text('{selected_popup_text}')"),
                            ]:
                                try:
                                    if await loc.count() > 0:
                                        await loc.first.click()
                                        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                                        break
                                except Exception:
                                    continue
                        break
                except Exception:
                    continue

        # 再チェック
        address1_val = await page.evaluate(
            "() => (document.querySelector('input[name$=\"address1\"]') || {}).value || ''"
        )
        logger.info("Prefecture/city after re-lookup: '%s'", address1_val)

    # Step 4: Ensure address2 hidden input exists (Yamato renders it as read-only
    # display after postal lookup, so the form may lack the actual input element).
    # Create it from registAddress2 + registChome if absent.
    await page.evaluate("""() => {
        const form = document.querySelector('form') || document.body;
        const existing = document.querySelector('input[name="viwb3040ActionBean.address2"]');
        if (existing) return;  // already present
        const regAddr2 = document.querySelector('input[name="viwb3040ActionBean.registAddress2"]');
        const regChome = document.querySelector('input[name="viwb3040ActionBean.registChome"]');
        const val = (regAddr2 ? regAddr2.value : '') + (regChome ? regChome.value : '');
        if (val) {
            const hidden = document.createElement('input');
            hidden.type = 'hidden';
            hidden.name = 'viwb3040ActionBean.address2';
            hidden.value = val;
            form.appendChild(hidden);
        }
    }""")

    # Step 5: Fill address fields
    if banchi_value:
        await _fill_input(page, YAMATO_SELECTORS["recipient_address3"], banchi_value)
    elif address_for_field:
        await _fill_input(page, YAMATO_SELECTORS["recipient_address3"], address_for_field)

    if go_value:
        await _fill_input(page, YAMATO_SELECTORS["recipient_address3opt"], go_value)

    if addr.building:
        await _fill_input(page, YAMATO_SELECTORS["recipient_address4"], addr.building)
    elif addr.address2:
        await _fill_input(page, YAMATO_SELECTORS["recipient_address4"], addr.address2)

    phone = addr.phone.replace("+81 ", "0").replace("+81", "0").replace("-", "")
    if phone:
        await _fill_input(page, YAMATO_SELECTORS["recipient_phone"], phone)

    if order.customer_email:
        await _toggle_notification(page, order.customer_email)

    await _uncheck_address_book(page)

    next_btn = page.locator(YAMATO_SELECTORS["next_btn"])
    await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    btn_count = await next_btn.count()
    if btn_count > 0:
        is_disabled = await next_btn.first.get_attribute("disabled")
        if is_disabled:
            # 次へボタンが無効なら、入力反映を促したうえで明示的に失敗させる。
            logger.info("Recipient next btn disabled; triggering form validation")
            await page.evaluate("""() => {
                document.querySelectorAll('input, select, textarea').forEach(el => {
                    el.dispatchEvent(new Event('change', {bubbles: true}));
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                    el.dispatchEvent(new Event('blur', {bubbles: true}));
                });
                if (typeof checkEmptyForm === 'function') checkEmptyForm();
            }""")
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            is_disabled = await next_btn.first.get_attribute("disabled")

        if is_disabled:
            raise RuntimeError(
                "Recipient step validation failed; next button is still disabled"
            )

        await _scroll_and_click(page, next_btn.first)
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
        logger.info("Recipient next clicked, URL=%s", _safe_url(page.url))

        # アドレス帳登録エラーバナー/ポップアップを検出して閉じる
        addr_book_error = await _dismiss_address_book_error(page)
        if addr_book_error:
            # エラーを閉じた後、再度「次へ」をクリック
            logger.info("Retrying recipient next after dismissing address book error")
            await _uncheck_address_book(page)
            await page.wait_for_timeout(TIMEOUT_INPUT_MS)
            next_btn2 = page.locator(YAMATO_SELECTORS["next_btn"])
            if await next_btn2.count() > 0:
                await _scroll_and_click(page, next_btn2.first)
                await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                logger.info("Recipient next re-clicked, URL=%s", _safe_url(page.url))

        await _assert_recipient_step_advanced(page)
    else:
        logger.warning("Recipient next btn (a#next) not found")

    # 「アドレス帳に登録しました」ポップアップを閉じる
    ok_btn = page.get_by_text("OK", exact=True)
    if await ok_btn.count() > 0 and await ok_btn.last.is_visible():
        await ok_btn.last.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
        logger.info("Dismissed address book registration popup")


async def _toggle_notification(page: "Page", email: str) -> None:
    """「お届け先へお届け予定をお知らせする」をチェックし、メールアドレスを入力する。"""
    toggled = False
    notify_cb = page.locator('input[name*="notifyFlg"]')
    if await notify_cb.count() > 0:
        cb = notify_cb.first
        try:
            checked = await cb.is_checked()
        except Exception:
            checked = False
        if not checked:
            # ビューポート外の場合があるため、JS scroll → scroll_into_view → force click の順で試す
            await page.evaluate("""() => {
                const el = document.querySelector('input[name*="notifyFlg"]');
                if (el) el.scrollIntoView({block: 'center'});
            }""")
            await page.wait_for_timeout(TIMEOUT_INPUT_MS)
            try:
                await cb.scroll_into_view_if_needed()
            except Exception:
                pass
            try:
                await cb.check(force=True)
                toggled = True
                logger.info("Toggled delivery notification via checkbox.check()")
            except Exception:
                # JS fallback: checked + click イベント発火
                try:
                    await page.evaluate("""() => {
                        const input = document.querySelector('input[name*="notifyFlg"]');
                        if (input) {
                            input.checked = true;
                            input.click();
                            input.dispatchEvent(new Event('input', {bubbles: true}));
                            input.dispatchEvent(new Event('change', {bubbles: true}));
                        }
                    }""")
                    toggled = True
                    logger.info("Toggled delivery notification via JS fallback")
                except Exception:
                    pass
    if not toggled:
        # notifyFlg が見つからない/効かない場合、テキストリンク/ラベルで探す
        for text in [
            "お届け先へお届け予定をお知らせする",
            "届け先への配達予定通知",
            "届け予定をお知らせ",
        ]:
            toggle_text = page.get_by_text(text, exact=False)
            if await toggle_text.count() > 0:
                try:
                    await toggle_text.first.scroll_into_view_if_needed()
                except Exception:
                    pass
                try:
                    await toggle_text.first.click(force=True)
                except Exception:
                    await page.evaluate(
                        """(needle) => {
                            const el = Array.from(document.querySelectorAll('label,span,a,div'))
                              .find(x => (x.innerText || '').includes(needle));
                            if (el) el.click();
                        }""",
                        text,
                    )
                await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                logger.info("Toggled delivery notification via text: %s", text)
                break

    # メールアドレス入力 — 通知チェック後にメール欄が展開されるのを待つ
    await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)

    # yoteiMailAddr を直接ターゲット (yoteiMailAddrInform は別フィールド)
    email_input = page.locator('input[type="email"]')
    if await email_input.count() == 0:
        email_input = page.locator('input[name$="yoteiMailAddr"]')
    if await email_input.count() > 0:
        # 非表示の場合は JS で表示を強制 & スクロール
        await page.evaluate("""() => {
            const input = document.querySelector('input[type="email"]')
                || document.querySelector('input[name$="yoteiMailAddr"]');
            if (!input) return;
            let el = input;
            for (let i = 0; i < 10 && el; i++) {
                const style = window.getComputedStyle(el);
                if (style.display === 'none') el.style.display = '';
                if (style.visibility === 'hidden') el.style.visibility = 'visible';
                if (style.maxHeight === '0px') el.style.maxHeight = 'none';
                el = el.parentElement;
            }
            input.scrollIntoView({block: 'center'});
        }""")
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)
        try:
            await email_input.first.fill(email, timeout=5000)
            logger.info("Filled notification email via Playwright fill")
        except Exception:
            # Playwright fill が効かない場合は JS で直接セット
            await page.evaluate(
                """(addr) => {
                    const input = document.querySelector('input[type="email"]')
                        || document.querySelector('input[name$="yoteiMailAddr"]');
                    if (input) {
                        // nativeInputValueSetter でフレームワークのバリデーションを通す
                        const nativeSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        nativeSetter.call(input, addr);
                        input.dispatchEvent(new Event('input', {bubbles: true}));
                        input.dispatchEvent(new Event('change', {bubbles: true}));
                        input.dispatchEvent(new Event('blur', {bubbles: true}));
                    }
                }""",
                email,
            )
            logger.info("Filled notification email via JS fallback")
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)
    else:
        logger.warning("No email input found on page")


async def _dismiss_address_book_error(page: "Page") -> bool:
    """「アドレス帳に登録できませんでした」エラーバナー/ポップアップを検出して閉じる。

    Returns True if the error was found and dismissed.
    """
    try:
        page_text = await page.evaluate(
            "() => (document.body && document.body.innerText) || ''"
        )
        if "アドレス帳に登録できませんでした" in page_text:
            logger.warning("Detected address book registration error banner")
            # OKボタンやCloseボタンでポップアップを閉じる
            for text in ["OK", "閉じる", "Close"]:
                btn = page.get_by_text(text, exact=True)
                if await btn.count() > 0:
                    for i in range(await btn.count()):
                        try:
                            if await btn.nth(i).is_visible():
                                await btn.nth(i).click()
                                await page.wait_for_timeout(TIMEOUT_INPUT_MS)
                                logger.info("Dismissed address book error via '%s' button", text)
                                return True
                        except Exception:
                            continue
            # ボタンが見つからない場合、エラー要素を非表示にしてみる
            await page.evaluate("""() => {
                document.querySelectorAll('.error, .alert, [class*="error"], [class*="alert"], [class*="popup"]').forEach(el => {
                    if ((el.innerText || '').includes('アドレス帳')) el.style.display = 'none';
                });
            }""")
            logger.info("Hid address book error elements via JS")
            return True
    except Exception as exc:
        logger.warning("Error checking for address book error banner: %s", exc)
    return False


async def _uncheck_address_book(page: "Page") -> None:
    """「アドレス帳に登録」チェックボックスをオフにする。

    Yamato uses 'addressListToRegister' hidden field.  The visible checkbox
    name varies, so we also force the hidden field to 'false' as a safety net.
    """
    try:
        # Try clicking the visible label to toggle off
        label = page.get_by_text("入力した情報をアドレス帳へ登録する", exact=False)
        if await label.count() > 0:
            is_reg = await page.evaluate(
                "() => (document.querySelector('input[name$=\"addressListToRegister\"]') || {}).value"
            )
            if is_reg == "true":
                await label.first.click()
                await page.wait_for_timeout(TIMEOUT_INPUT_MS)
                logger.info("Unchecked address book registration via label")
    except Exception:
        pass

    # Safety net: force the hidden field to false regardless
    try:
        await page.evaluate("""() => {
            const el = document.querySelector('input[name$="addressListToRegister"]');
            if (el) el.value = 'false';
        }""")
    except Exception:
        logger.warning("Could not force addressListToRegister to false")


def _normalize_for_match(text: str) -> str:
    """Normalize text for fuzzy matching: NFKC, collapse whitespace, strip 様."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _sender_matches(candidate_text: str, sender_name: str) -> bool:
    """Check if candidate text contains the sender name after normalization.

    Handles full-width/half-width differences, extra spaces, and trailing 様.
    """
    norm_candidate = _normalize_for_match(candidate_text)
    norm_sender = _normalize_for_match(sender_name)

    # Direct normalized match
    if norm_sender in norm_candidate:
        return True

    # Try without trailing 様 on both sides
    norm_sender_no_sama = norm_sender.rstrip("様").strip()
    norm_candidate_no_sama = norm_candidate.replace("様", " ").strip()
    if norm_sender_no_sama and norm_sender_no_sama in norm_candidate_no_sama:
        return True

    return False


async def _select_sender_from_address_book(
    page: "Page", settings: Settings
) -> None:
    sender_name = settings.sender_name
    if not sender_name:
        raise RuntimeError("SENDER_NAME is not configured")

    # アドレス帳リンクをクリック (複数パターン対応)
    addr_book_clicked = False
    for addr_text in ["アドレス帳から選択", "アドレス帳"]:
        addr_book = page.get_by_text(addr_text, exact=False)
        if await addr_book.count() > 0:
            await _scroll_and_click(page, addr_book.first)
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            addr_book_clicked = True
            logger.info("Clicked address book link: %s", addr_text)
            break

    if not addr_book_clicked:
        logger.warning("Address book link not found; attempting direct sender input")
        await _fill_sender_info(page, settings)
        return

    # アドレス帳ページへの遷移を待つ
    await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    logger.info("Sender page URL after address book click: %s", _safe_url(page.url))

    # ラジオボタンの読み込みをリトライ付きで待機
    radio_entries: list[dict] = []
    for attempt in range(5):
        radio_entries = await page.evaluate("""() => {
            const radios = document.querySelectorAll('input[type="radio"]');
            return Array.from(radios).map((r, i) => {
                let p = r.parentElement;
                for (let j = 0; j < 5 && p; j++) {
                    if (p.innerText && p.innerText.length > 10)
                        return {index: i, text: p.innerText.substring(0, 300)};
                    p = p.parentElement;
                }
                return {index: i, text: ''};
            });
        }""")
        if len(radio_entries) > 0:
            break
        logger.info("Address book: no radio entries yet (attempt %d/5), waiting...", attempt + 1)
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)

    if len(radio_entries) == 0:
        page_title = await page.evaluate("() => document.title || ''")
        logger.info("Sender page title: %s (may still be on recipient page)", page_title)

    logger.info(
        "Sender address book: %d radio entries found. Looking for '%s'",
        len(radio_entries), sender_name,
    )
    for i, entry in enumerate(radio_entries):
        entry_text = entry.get("text", "")
        logger.info("  entry[%d]: %s", i, entry_text[:80].replace("\n", " | "))

    for entry in radio_entries:
        entry_text = entry.get("text", "")
        if _sender_matches(entry_text, sender_name):
            idx = entry["index"]
            radio = page.locator("input[type='radio']").nth(idx)
            parent_label = radio.locator("xpath=ancestor::label")
            if await parent_label.count() > 0:
                await parent_label.first.click()
            else:
                parent_div = radio.locator("xpath=ancestor::div").first
                await parent_div.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Selected sender (matched): %s", sender_name)
            return

    # フォールバック: アドレス帳UIが壊れている/0件に見える場合は依頼主情報を直接入力
    logger.warning(
        "Sender '%s' not found in address book (entries=%d). Falling back to manual sender input.",
        sender_name, len(radio_entries),
    )
    await _fill_sender_info(page, settings)


async def _fill_sender_info(page: "Page", settings: Settings) -> None:
    """依頼主情報を直接入力するフォールバック。"""
    if settings.sender_name:
        sender_name = settings.sender_name.replace("様", "").strip()
        if " " in sender_name:
            last, first = sender_name.split(" ", 1)
        else:
            last, first = sender_name, ""
        await _fill_input(page, YAMATO_SELECTORS["sender_last_name"], last)
        if first:
            await _fill_input(page, YAMATO_SELECTORS["sender_first_name"], first)

    postal = re.sub(r"\D", "", settings.sender_postal_code or "")
    if postal:
        await _fill_input(page, YAMATO_SELECTORS["sender_zip"], postal)

    if settings.sender_address1:
        await _fill_input(page, YAMATO_SELECTORS["sender_address3"], settings.sender_address1)
    if settings.sender_address2:
        await _fill_input(page, YAMATO_SELECTORS["sender_address4"], settings.sender_address2)

    phone = (settings.sender_phone or "").replace("-", "")
    if phone:
        await _fill_input(page, YAMATO_SELECTORS["sender_phone"], phone)

    await _uncheck_address_book(page)
    logger.info("Filled sender info manually as fallback")


async def _confirm_sender_info(page: "Page") -> None:
    # 「次へ」を最大3回クリック: アドレス帳選択→依頼主情報確認→発送場所設定
    # 手動入力フォールバック時はステップが増える場合がある
    for step in range(3):
        await _uncheck_address_book(page)
        next_btn = page.get_by_text("次へ", exact=True)
        if await next_btn.count() > 0:
            await _scroll_and_click(page, next_btn.first)
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.debug("Sender confirm step %d, URL=%s", step, _safe_url(page.url))

            # アドレス帳エラー/登録ポップアップを閉じる
            await _dismiss_address_book_error(page)
            ok_btn = page.get_by_text("OK", exact=True)
            if await ok_btn.count() > 0 and await ok_btn.last.is_visible():
                await ok_btn.last.click()
                await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                logger.info("Dismissed popup after sender confirm step %d", step)
        else:
            break


async def _select_shipping_location(page: "Page", settings: Settings) -> None:
    preferred = settings.preferred_shipping_location
    logger.info("Selecting shipping location (preferred=%s)", preferred or "(none)")

    # ページ上のラジオボタン / リンクから発送場所を選択
    selected = False

    # 方法1: preferred_shipping_location のテキストマッチ (部分一致)
    if preferred:
        loc = page.get_by_text(preferred, exact=False)
        if await loc.count() > 0:
            await loc.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Selected shipping location by preferred text: %s", preferred)
            selected = True

    # 方法2: 「セブンイレブン」を含むラジオボタンや要素を探す
    if not selected and preferred and "セブン" in preferred:
        seven_loc = page.get_by_text("セブン", exact=False)
        if await seven_loc.count() > 0:
            await seven_loc.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Selected shipping location by partial match: セブン")
            selected = True

    # 方法3: 登録済みの場所一覧からラジオボタンで選択
    if not selected and preferred:
        radio_entries = await page.evaluate("""() => {
            const radios = document.querySelectorAll('input[type="radio"]');
            return Array.from(radios).map((r, i) => {
                let p = r.parentElement;
                for (let j = 0; j < 5 && p; j++) {
                    if (p.innerText && p.innerText.length > 3)
                        return {index: i, text: p.innerText.substring(0, 200)};
                    p = p.parentElement;
                }
                return {index: i, text: ''};
            });
        }""")
        for entry in radio_entries:
            entry_text = entry.get("text", "")
            if preferred in entry_text or ("セブン" in preferred and "セブン" in entry_text):
                idx = entry["index"]
                radio = page.locator("input[type='radio']").nth(idx)
                parent_label = radio.locator("xpath=ancestor::label")
                if await parent_label.count() > 0:
                    await parent_label.first.click()
                else:
                    await radio.first.click(force=True)
                await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                logger.info("Selected shipping location via radio: %s", entry_text[:60])
                selected = True
                break

    # フォールバック: 「近くから発送」
    if not selected:
        fallback = page.get_by_text("近くから発送", exact=False)
        if await fallback.count() > 0:
            await fallback.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Selected fallback shipping location: 近くから発送")
            selected = True

    if not selected:
        logger.warning("No shipping location found on page")

    # 「次へ」ボタンで進む
    next_btn = page.get_by_text("次へ", exact=True)
    if await next_btn.count() > 0:
        await next_btn.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
        logger.debug("Shipping location next, URL=%s", _safe_url(page.url))


async def _fill_delivery_datetime(page: "Page", order: RentalOrder) -> None:
    logger.info(
        "Delivery datetime: date=%s, time=%s",
        order.delivery_date,
        order.delivery_time.value if hasattr(order.delivery_time, "value") else order.delivery_time,
    )
    if not order.delivery_date:
        logger.warning("No delivery_date set on order; skipping delivery datetime")
        return

    try:
        delivery_dt = datetime.strptime(order.delivery_date, "%Y%m%d")
    except ValueError:
        logger.warning("Invalid delivery_date: %s", order.delivery_date)
        return

    # --- お届け予定日セクションへのナビゲーション ---
    # select が見つかるまで複数の方法で「変更」ボタンを探す
    shipping_select = page.locator(YAMATO_SELECTORS["shipping_date"])
    if await shipping_select.count() == 0:
        # 方法1: 「お届け予定日」付近の「変更」テキストリンク/ボタン
        for change_selector in [
            "button#warning",
            'a:has-text("変更")',
            'button:has-text("変更")',
        ]:
            change_btn = page.locator(change_selector)
            if await change_btn.count() > 0:
                await change_btn.first.click()
                await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                logger.info("Clicked delivery date change via: %s", change_selector)
                break

        # モーダルが出た場合 OK をクリック
        ok_btn = page.get_by_text("OK", exact=True)
        if await ok_btn.count() > 0 and await ok_btn.last.is_visible():
            await ok_btn.last.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)

        shipping_select = page.locator(YAMATO_SELECTORS["shipping_date"])

    # select がまだ見つからない場合、全 select 要素をダンプしてデバッグ
    if await shipping_select.count() == 0:
        all_selects = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('select')).map(s => ({
                name: s.name, id: s.id,
                options: Array.from(s.options).slice(0, 5).map(o => o.value + ':' + o.text)
            }));
        }""")
        logger.warning("Delivery date selects not found. All selects on page: %s", all_selects)
        logger.warning("Page URL: %s", _safe_url(page.url))
        return

    # --- 発送日・到着日・時間帯の各 select を取得 ---
    delivery_select = page.locator(YAMATO_SELECTORS["delivery_date"])
    time_select_all = page.locator("select#timeToReceiveByTZone")
    if await time_select_all.count() > 0:
        time_select = time_select_all.first
    else:
        time_select = page.locator(YAMATO_SELECTORS["delivery_time"]).first

    # 発送日 select の全オプションをログ出力
    shipping_options = await shipping_select.first.evaluate("""el => {
        return Array.from(el.options).map(o => o.value);
    }""")
    logger.info("Available shipping dates: %s", shipping_options)

    # 発送日候補: 到着希望日の前日優先 → 2日前 → 当日
    raw_ship_dates = [
        (delivery_dt - timedelta(days=1)).strftime("%Y%m%d"),
        (delivery_dt - timedelta(days=2)).strftime("%Y%m%d"),
        delivery_dt.strftime("%Y%m%d"),
    ]
    ship_dates = list(dict.fromkeys(raw_ship_dates))
    logger.info("Will try shipping dates: %s for delivery %s", ship_dates, order.delivery_date)

    combination_set = False
    failure_reasons: list[str] = []
    time_value = (
        order.delivery_time.value
        if hasattr(order.delivery_time, "value")
        else str(order.delivery_time)
    )
    for ship_date in ship_dates:
        option = shipping_select.first.locator(f'option[value="{ship_date}"]')
        if await option.count() == 0:
            logger.debug("Ship date %s not available", ship_date)
            failure_reasons.append(f"ship={ship_date}: shipping date unavailable")
            continue

        await shipping_select.first.select_option(value=ship_date)
        await page.wait_for_timeout(TIMEOUT_DROPDOWN_UPDATE_MS)
        logger.info("Selected shipping date: %s", ship_date)

        # 到着日 select の再取得 (発送日変更でオプションが動的更新される)
        delivery_select = page.locator(YAMATO_SELECTORS["delivery_date"])
        if await delivery_select.count() == 0:
            logger.warning("Delivery date select not found after setting ship date")
            failure_reasons.append(f"ship={ship_date}: delivery date select missing")
            continue

        delivery_options = await delivery_select.first.evaluate("""el => {
            return Array.from(el.options).map(o => o.value);
        }""")
        logger.info("Available delivery dates for ship=%s: %s", ship_date, delivery_options)

        delivery_option = delivery_select.first.locator(
            f'option[value="{order.delivery_date}"]'
        )
        if await delivery_option.count() == 0:
            logger.debug("Delivery date %s not in options for ship=%s", order.delivery_date, ship_date)
            failure_reasons.append(
                f"ship={ship_date}: delivery date {order.delivery_date} unavailable"
            )
            continue

        await delivery_select.first.select_option(value=order.delivery_date)
        await page.wait_for_timeout(TIMEOUT_DROPDOWN_UPDATE_MS)
        logger.info("Selected delivery date: %s", order.delivery_date)

        # --- 時間帯の設定 ---
        if not time_value or time_value == "0":
            logger.info("No delivery time requested; skipping time selection")
            combination_set = True
            break

        # 時間帯 select の再取得 (到着日変更で時間帯オプションが変わる)
        time_select_all = page.locator("select#timeToReceiveByTZone")
        if await time_select_all.count() > 0:
            time_select = time_select_all.first
        else:
            time_select = page.locator(YAMATO_SELECTORS["delivery_time"]).first

        if await time_select.count() == 0:
            logger.warning("Time select not found")
            failure_reasons.append(f"ship={ship_date}: time select missing")
            continue

        enabled_options = await time_select.evaluate("""el => {
            return Array.from(el.options).map(o => ({
                value: o.value, text: o.text, disabled: o.disabled
            }));
        }""")
        logger.info("Time options: %s", enabled_options)

        target_enabled = any(
            o["value"] == time_value and not o["disabled"]
            for o in enabled_options
        )
        if not target_enabled:
            available_times = [
                f"{o['value']}:{o['text']}"
                for o in enabled_options
                if not o["disabled"] and o["value"] not in ("0", "")
            ]
            logger.info(
                "Requested delivery time %s unavailable for ship=%s, delivery=%s; trying next ship date. Available=%s",
                time_value,
                ship_date,
                order.delivery_date,
                available_times,
            )
            failure_reasons.append(
                f"ship={ship_date}: requested time {time_value} unavailable; available={available_times}"
            )
            continue

        try:
            await time_select.select_option(value=time_value, timeout=5000)
        except Exception:
            # JS フォールバック: select_option が効かない場合
            await page.evaluate(f"""() => {{
                const sel = document.querySelector('#timeToReceiveByTZone')
                    || document.querySelector('select[name="viwb4100ActionBean.timeToReceive"]');
                if (sel) {{
                    sel.value = '{time_value}';
                    sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}""")
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)
        logger.info(
            "Set delivery: ship=%s, deliver=%s, time=%s",
            ship_date, order.delivery_date, time_value,
        )
        combination_set = True
        break

    if not combination_set:
        # Draft-first: 完全一致が見つからなくても、配達日だけでもセットしてドラフト作成を継続する。
        # 検証フェーズでミスマッチとして報告される。
        logger.warning(
            "DRAFT-FIRST: exact delivery combination unavailable "
            "(delivery_date=%s, delivery_time=%s, candidates=%s, reasons=%s). "
            "Attempting fallback to proceed with draft creation.",
            order.delivery_date, time_value or "0", ship_dates, failure_reasons,
        )
        # フォールバック: 発送日→配達日だけをセットし、時間帯は指定なしで続行
        fallback_set = False
        for ship_date in ship_dates:
            option = shipping_select.first.locator(f'option[value="{ship_date}"]')
            if await option.count() == 0:
                continue
            await shipping_select.first.select_option(value=ship_date)
            await page.wait_for_timeout(TIMEOUT_DROPDOWN_UPDATE_MS)
            delivery_select = page.locator(YAMATO_SELECTORS["delivery_date"])
            if await delivery_select.count() == 0:
                continue
            delivery_option = delivery_select.first.locator(
                f'option[value="{order.delivery_date}"]'
            )
            if await delivery_option.count() > 0:
                await delivery_select.first.select_option(value=order.delivery_date)
                await page.wait_for_timeout(TIMEOUT_DROPDOWN_UPDATE_MS)
                logger.info(
                    "DRAFT-FIRST fallback: set ship=%s, deliver=%s, time=none",
                    ship_date, order.delivery_date,
                )
                fallback_set = True
                break
        if not fallback_set:
            # 配達日すらセットできない場合は真にブロッキング
            raise RuntimeError(
                "Could not satisfy requested delivery combination "
                "(even fallback failed): "
                f"delivery_date={order.delivery_date}, "
                f"delivery_time={time_value or '0'}, "
                f"candidates={ship_dates}, "
                f"reasons={failure_reasons}"
            )

    # 「設定する」または「次へ」で確定
    for btn_text in ["設定する", "次へ"]:
        btn = page.get_by_text(btn_text, exact=True)
        if await btn.count() > 0:
            await btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Delivery datetime confirmed with '%s'", btn_text)
            break


async def _scrape_confirmation_page(page: "Page") -> dict[str, str]:
    """確認ページからフォーム入力値とページテキストを取得する。

    Yamato の確認ページは2パターン:
    1. フォーム入力値が残っている (hidden / readonly input)
    2. テキスト表示のみ (入力値が DOM テキストに展開されている)

    両方のパターンに対応し、取得できた値を返す。
    """
    scraped: dict[str, str] = {}

    # --- パターン1: フォーム入力値の直接読み取り ---
    form_values = await page.evaluate("""() => {
        const result = {};
        const fields = {
            'recipient_last_name': 'viwb3040ActionBean.lastName',
            'recipient_first_name': 'viwb3040ActionBean.firstName',
            'recipient_zip': 'viwb3040ActionBean.zipCode',
            'recipient_address3': 'viwb3040ActionBean.address3',
            'recipient_address3opt': 'viwb3040ActionBean.address3opt',
            'recipient_address4': 'viwb3040ActionBean.address4',
            'recipient_phone': 'viwb3040ActionBean.phoneNumber',
            'sender_last_name': 'viwb3130ActionBean.lastName',
            'sender_first_name': 'viwb3130ActionBean.firstName',
            'sender_zip': 'viwb3130ActionBean.zipCode',
            'notification_email': 'yoteiMailAddr',
        };
        for (const [key, name] of Object.entries(fields)) {
            const el = document.querySelector(`input[name="${name}"]`)
                || document.querySelector(`input[name*="${name}"]`);
            if (el) result[key] = el.value || '';
        }
        // サイズ (checked radio)
        const sizeRadio = document.querySelector(
            'input[name="viwb2050ActionBean.size"]:checked'
        );
        if (sizeRadio) result['package_size'] = sizeRadio.value || '';

        // 配達日・時間 (select)
        const deliveryDate = document.querySelector(
            'select[name="viwb4100ActionBean.dateToReceive"]'
        );
        if (deliveryDate) result['delivery_date'] = deliveryDate.value || '';

        const deliveryTime = document.querySelector('#timeToReceiveByTZone')
            || document.querySelector('select[name="viwb4100ActionBean.timeToReceive"]');
        if (deliveryTime) result['delivery_time'] = deliveryTime.value || '';

        return result;
    }""")

    for k, v in form_values.items():
        if v:
            scraped[k] = v

    # --- パターン2: ページテキストからの抽出 ---
    # 確認画面ではフォーム要素がない場合があるため、表示テキストも取得
    page_text = await page.evaluate("""() => {
        const body = document.querySelector('body');
        return body ? body.innerText : '';
    }""")
    scraped["_page_text"] = page_text[:3000]  # 先頭3000文字のスニペット

    # テキストから住所を抽出 (フォーム値がない場合のフォールバック)
    if "recipient_address3" not in scraped:
        # 「〒」の後の郵便番号とその下の住所行を探す
        zip_match = re.search(r"〒\s*(\d{3}-?\d{4})", page_text)
        if zip_match:
            scraped.setdefault("recipient_zip_display", zip_match.group(1).replace("-", ""))

    # 確認画面のテキストからキーバリューペアを抽出
    # 典型パターン: "お届け先\n山田 太郎\n〒150-0001\n東京都..."
    text_values = await page.evaluate("""() => {
        const result = {};
        // dt/dd パターン (定義リスト形式)
        document.querySelectorAll('dt, th').forEach(dt => {
            const dd = dt.nextElementSibling;
            if (dd) {
                const key = dt.textContent.trim();
                const val = dd.textContent.trim();
                if (key && val) result[key] = val;
            }
        });
        // ラベル + 値パターン (span/div 形式)
        document.querySelectorAll('.label, .item-label, [class*="label"]').forEach(label => {
            const sib = label.nextElementSibling;
            if (sib) {
                const key = label.textContent.trim();
                const val = sib.textContent.trim();
                if (key && val) result[key] = val;
            }
        });
        return result;
    }""")

    for k, v in text_values.items():
        scraped[f"_text_{k}"] = v

    return scraped


def _build_expected_values(
    order: RentalOrder, settings: "Settings",
) -> dict[str, str]:
    """RentalOrder + Settings から期待値の辞書を生成する。"""
    addr = order.shipping_address
    expected: dict[str, str] = {}

    # 宛先
    expected["recipient_last_name"] = addr.last_name
    expected["recipient_first_name"] = addr.first_name
    expected["recipient_zip"] = addr.postal_code.replace("-", "")
    if addr.building:
        expected["recipient_address4"] = addr.building

    # 丁目・番地 — 期待値は address1 のパース結果ベース
    if addr.chome:
        expected["recipient_chome"] = addr.chome
    if addr.banchi:
        expected["recipient_banchi"] = addr.banchi

    # サイズ
    radio_value = PACKAGE_SIZE_TO_RADIO_VALUE.get(order.package_size, "C")
    expected["package_size"] = radio_value

    # 配達日時
    if order.delivery_date:
        expected["delivery_date"] = order.delivery_date
    time_val = (
        order.delivery_time.value
        if hasattr(order.delivery_time, "value")
        else str(order.delivery_time)
    )
    if time_val and time_val != "0":
        expected["delivery_time"] = time_val

    # 発送元 (sender_name)
    if settings.sender_name:
        expected["sender_name"] = settings.sender_name.replace("様", "").strip()

    # 通知メール
    if order.customer_email:
        expected["notification_email"] = order.customer_email

    return expected


def _fuzzy_match(expected: str, actual: str) -> bool:
    """正規化して比較。全角/半角、空白、「様」の差異を吸収する。"""
    if not expected and not actual:
        return True
    if not expected or not actual:
        return False
    e = unicodedata.normalize("NFKC", expected).strip()
    a = unicodedata.normalize("NFKC", actual).strip()
    # 完全一致
    if e == a:
        return True
    # 一方が他方を含む (住所の部分一致)
    if e in a or a in e:
        return True
    # 数字のみ比較 (丁目番地)
    e_digits = re.sub(r"\D", "", e)
    a_digits = re.sub(r"\D", "", a)
    if e_digits and a_digits and e_digits == a_digits:
        return True
    return False


async def _verify_confirmation(
    page: "Page",
    order: RentalOrder,
    settings: "Settings",
) -> VerificationReport:
    """確認ページの値を期待値と比較し、VerificationReport を生成・保存する。"""
    report = VerificationReport(
        order_number=order.order_number,
        timestamp=datetime.now().isoformat(),
    )

    try:
        scraped = await _scrape_confirmation_page(page)
        expected = _build_expected_values(order, settings)

        report.page_text_snippet = scraped.get("_page_text", "")[:1000]
        page_text = scraped.get("_page_text", "")

        # --- フィールドごとの比較 ---

        # 1. 宛先名 (姓)
        actual_last = scraped.get("recipient_last_name", "")
        if not actual_last and page_text:
            # ページテキストに名前が含まれるかチェック
            actual_last = (
                expected.get("recipient_last_name", "")
                if expected.get("recipient_last_name", "") in page_text
                else ""
            )
        report.add(
            "recipient_last_name",
            expected.get("recipient_last_name", ""),
            actual_last,
        )

        # 2. 宛先名 (名)
        actual_first = scraped.get("recipient_first_name", "")
        if not actual_first and page_text:
            actual_first = (
                expected.get("recipient_first_name", "")
                if expected.get("recipient_first_name", "") in page_text
                else ""
            )
        report.add(
            "recipient_first_name",
            expected.get("recipient_first_name", ""),
            actual_first,
        )

        # 3. 郵便番号
        actual_zip = scraped.get(
            "recipient_zip",
            scraped.get("recipient_zip_display", ""),
        )
        if not actual_zip and page_text:
            zip_match = re.search(r"(\d{3})-?(\d{4})", page_text)
            if zip_match:
                actual_zip = zip_match.group(1) + zip_match.group(2)
        report.add(
            "recipient_zip",
            expected.get("recipient_zip", ""),
            actual_zip,
        )

        # 4. 住所3 (丁目)
        actual_addr3 = scraped.get("recipient_address3", "")
        report.add(
            "recipient_address3_chome",
            expected.get("recipient_chome", ""),
            actual_addr3,
        )

        # 5. 住所3opt (番地・号)
        actual_addr3opt = scraped.get("recipient_address3opt", "")
        report.add(
            "recipient_address3opt_banchi",
            expected.get("recipient_banchi", ""),
            actual_addr3opt,
        )

        # 6. 建物名
        actual_addr4 = scraped.get("recipient_address4", "")
        report.add(
            "recipient_address4_building",
            expected.get("recipient_address4", ""),
            actual_addr4,
        )

        # 7. サイズ
        actual_size = scraped.get("package_size", "")
        if not actual_size and page_text:
            for label, val in [
                ("宅急便コンパクト", "C"),
                ("宅急便 LL", "LL"),
                ("宅急便 L", "L"),
                ("宅急便 M", "M"),
                ("宅急便 S", "S"),
            ]:
                if label in page_text:
                    actual_size = val
                    break
        report.add(
            "package_size",
            expected.get("package_size", ""),
            actual_size,
        )

        # 8. 配達日
        actual_date = scraped.get("delivery_date", "")
        if not actual_date and page_text and expected.get("delivery_date"):
            # YYYYMMDD → 表示形式 "YYYY/MM/DD" or "MM月DD日" をテキストから探す
            exp_date = expected["delivery_date"]
            if len(exp_date) == 8:
                formatted = f"{exp_date[:4]}/{exp_date[4:6]}/{exp_date[6:8]}"
                jp_formatted = f"{int(exp_date[4:6])}月{int(exp_date[6:8])}日"
                if exp_date in page_text:
                    actual_date = exp_date
                elif formatted in page_text:
                    actual_date = exp_date  # 表示形式は違うが値は一致
                elif jp_formatted in page_text:
                    actual_date = exp_date
        report.add(
            "delivery_date",
            expected.get("delivery_date", ""),
            actual_date,
        )

        # 9. 配達時間
        actual_time = scraped.get("delivery_time", "")
        if not actual_time and page_text:
            actual_time = _extract_delivery_time_from_text(page_text)
        report.add(
            "delivery_time",
            expected.get("delivery_time", ""),
            actual_time,
        )

        # 10. 発送元
        actual_sender = scraped.get("sender_last_name", "")
        sender_first = scraped.get("sender_first_name", "")
        if sender_first:
            actual_sender = f"{actual_sender} {sender_first}".strip()
        if not actual_sender and page_text and expected.get("sender_name"):
            actual_sender = (
                expected["sender_name"]
                if expected["sender_name"] in page_text
                else ""
            )
        report.add(
            "sender_name",
            expected.get("sender_name", ""),
            actual_sender,
        )

        # 11. 通知メール
        actual_email = scraped.get("notification_email", "")
        if not actual_email or "@" not in actual_email:
            # フォーム要素が存在しない確認ページでは input 値が取れないため
            # ページテキストから期待するメールアドレスの存在を確認する
            if expected.get("notification_email") and page_text:
                if expected["notification_email"] in page_text:
                    actual_email = expected["notification_email"]
                else:
                    # 一般的なメールアドレスパターンで抽出を試みる
                    email_matches = re.findall(
                        r"[\w.+-]+@[\w.-]+\.\w+", page_text,
                    )
                    for em in email_matches:
                        if em == expected["notification_email"]:
                            actual_email = em
                            break
        if expected.get("notification_email"):
            report.add(
                "notification_email",
                expected["notification_email"],
                actual_email,
            )

        # fuzzy match で mismatch リストを再評価
        # strict match で不一致でも fuzzy で一致していれば mismatch から除外しない
        # （厳密な差分を残すことで改善材料にする）
        report.verified = True

    except Exception as e:
        logger.warning("Verification scrape failed: %s", e)
        report.page_text_snippet = f"ERROR: {e}"

    return report


def _save_verification_report(report: VerificationReport) -> str:
    """検証レポートを JSON ファイルに保存し、パスを返す。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_order = re.sub(r"[^\w\-]", "", report.order_number)
    filename = f"{safe_order}_{ts}.json"
    filepath = VERIFICATION_DIR / filename

    # page_text_snippet 内の個人情報をマスクしないが、
    # expected/actual にはオーダーの情報しか入らないのでそのまま保存
    data = report.model_dump()
    # _page_text は巨大になる可能性があるので切り詰め済み
    filepath.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Verification report saved: %s", filepath)
    return str(filepath)


def _log_verification_summary(report: VerificationReport) -> None:
    """検証結果のサマリーをログ出力する。"""
    total = len(report.fields)
    mismatches = len(report.mismatches)

    if mismatches == 0:
        logger.info(
            "VERIFICATION [%s]: ALL MATCH (%d fields checked)",
            report.order_number,
            total,
        )
    else:
        logger.warning(
            "VERIFICATION [%s]: %d MISMATCH(ES) out of %d fields",
            report.order_number,
            mismatches,
            total,
        )
        for m in report.mismatches:
            logger.warning(
                "  MISMATCH %s: expected=%r, actual=%r",
                m.field,
                m.expected,
                m.actual,
            )


async def _save_draft(page: "Page") -> None:
    # 「保存して別の荷物を送る」で下書き保存
    save_btn = page.locator("a#saveReturn")
    if await save_btn.count() > 0:
        await save_btn.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
        logger.info("Clicked saveReturn")

        # 確認モーダルが出たら OK をクリック
        ok_btn = page.get_by_text("OK", exact=True)
        if await ok_btn.count() > 0 and await ok_btn.last.is_visible():
            await ok_btn.last.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Confirmed save modal")
    else:
        # フォールバック: 「次へ」(支払いへ進む) を試す
        pay_btn = page.locator("a#doPaymentForward")
        if await pay_btn.count() > 0:
            await pay_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Clicked payment forward")
        else:
            logger.warning("No save/submit button found")

    await page.wait_for_timeout(TIMEOUT_DIALOG_MS)


async def _check_session_error(page: "Page") -> None:
    content = await page.content()
    if "本サービスを継続する" in content:
        raise RuntimeError("Yamato session expired or invalid state")


async def _scroll_and_click(page: "Page", locator, timeout_ms: int = 5000) -> None:
    """スクロール → クリック。viewport 外の要素にも対応。"""
    # Step 1: JS scrollIntoView で要素をビュー内に持ってくる
    try:
        await locator.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)
    except Exception:
        pass
    # Step 2: 通常クリック → force クリック → JS click の順で試す
    try:
        await locator.click(timeout=timeout_ms)
        return
    except Exception:
        pass
    try:
        await locator.click(force=True)
        return
    except Exception:
        pass
    # Step 3: JS 直接クリック (最終手段)
    await locator.evaluate("el => el.click()")
    await page.wait_for_timeout(TIMEOUT_INPUT_MS)


async def _fill_input(
    page: "Page", selector: str, value: str, timeout_ms: int = TIMEOUT_INPUT_MS
) -> None:
    locator = page.locator(selector)
    if await locator.count() > 0:
        await locator.first.fill(value)
        await locator.first.dispatch_event("input")
        await page.wait_for_timeout(timeout_ms)
