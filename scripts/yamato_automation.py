import logging
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from scripts.config import Settings, get_settings
from scripts.models import PackageSize, RentalOrder, ShippingResult, ShippingStatus

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from playwright.async_api import Dialog, Page

QR_CODE_DIR = Path("qr_codes")
QR_CODE_DIR.mkdir(exist_ok=True)

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

            await _save_draft(page)
            logger.info("STEP: save_draft done")

            screenshot_path = str(QR_CODE_DIR / f"{order.order_number}_confirmation.png")
            await page.screenshot(path=screenshot_path, full_page=True)

            return ShippingResult(
                order_id=order.order_id,
                order_number=order.order_number,
                status=ShippingStatus.COMPLETED,
                qr_code_path=screenshot_path,
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

    # Shopify JP stores firstName=姓, lastName=名 (逆) なので swap して入力
    await _fill_input(page, YAMATO_SELECTORS["recipient_last_name"], addr.first_name)
    if addr.last_name:
        await _fill_input(page, YAMATO_SELECTORS["recipient_first_name"], addr.last_name)

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
        if not chome_to_select and addr.address1:
            match = re.search(r"(\d+)-(\d+)(?:-(\d+))?$", addr.address1)
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
                    logger.info(
                        "Parsed chome=%s, banchi=%s, go=%s (confirmed in popup)",
                        chome_to_select, banchi_value, go_value,
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
                    logger.info("Clicked section: %s", matched_option)

                    # Parse remaining for banchi-go (e.g., "30-12" -> banchi=30, go=12)
                    remaining_match = re.match(r"(\d+)(?:-(\d+))?$", remaining_address.lstrip("-"))
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

    # Step 3: If popup is still open and unclicked, dismiss with first option as fallback
    if has_popup and not popup_clicked:
        logger.info("Popup still open; clicking first option as fallback to dismiss")
        try:
            first_link = popup_frame.locator("a").first
            if await first_link.count() > 0:
                first_text = await first_link.inner_text()
                await first_link.click()
                await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                popup_clicked = True
                logger.info("Fallback: clicked '%s'", first_text)
                # Keep raw address1 in address_for_field since we didn't match properly
        except Exception:
            logger.warning("Failed to click fallback popup option")

    if not has_popup and addr.address1:
        logger.info("No address popup after postal lookup; using raw address1: %s", addr.address1)

    # Step 4: Fill address fields
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
    if await next_btn.count() > 0:
        is_disabled = await next_btn.first.get_attribute("disabled")
        if not is_disabled:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)

    # 「アドレス帳に登録しました」ポップアップを閉じる
    ok_btn = page.get_by_text("OK", exact=True)
    if await ok_btn.count() > 0 and await ok_btn.last.is_visible():
        await ok_btn.last.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
        logger.info("Dismissed address book registration popup")


async def _toggle_notification(page: "Page", email: str) -> None:
    notify_cb = page.locator('input[name*="notifyFlg"]')
    if await notify_cb.count() > 0:
        if not await notify_cb.first.is_checked():
            # ラベルをクリックして通知を有効化
            notify_label = notify_cb.first.locator("xpath=ancestor::label")
            if await notify_label.count() > 0:
                await notify_label.first.click()
            else:
                toggle_text = page.get_by_text("届け先への配達予定通知", exact=False)
                if await toggle_text.count() > 0:
                    await toggle_text.first.click()
                else:
                    await notify_cb.first.click(force=True)
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Toggled delivery notification on")

    email_input = page.locator('input[name*="mailAddress"]')
    if await email_input.count() == 0:
        email_input = page.locator('input[type="email"]')
    if await email_input.count() > 0:
        if await email_input.first.is_visible():
            await email_input.first.fill(email)
            await page.wait_for_timeout(TIMEOUT_INPUT_MS)
        else:
            logger.warning("Email input not visible, skipping notification email")


async def _uncheck_address_book(page: "Page") -> None:
    cb = page.locator('input[name*="addAddressBook"]')
    if await cb.count() > 0 and await cb.first.is_checked():
        label = page.get_by_text("入力した情報をアドレス帳へ登録する", exact=False)
        if await label.count() > 0:
            await label.first.click()
            logger.info("Unchecked address book registration")
        else:
            # フォールバック: ラベル要素を辿ってクリック
            parent_label = cb.first.locator("xpath=ancestor::label")
            if await parent_label.count() > 0:
                await parent_label.first.click()
            else:
                await cb.first.click(force=True)
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)


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
    addr_book = page.get_by_text("アドレス帳から選択", exact=False)
    if await addr_book.count() > 0:
        await addr_book.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)

    sender_name = settings.sender_name
    if not sender_name:
        raise RuntimeError("SENDER_NAME is not configured")

    # ラジオボタンの親テキストから送り主を探してクリック
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

    logger.info(
        "Sender address book: %d radio entries found. Looking for '%s'",
        len(radio_entries), sender_name,
    )
    for i, entry in enumerate(radio_entries):
        entry_text = entry.get("text", "")
        # Log first 80 chars of each entry for debugging
        logger.info("  entry[%d]: %s", i, entry_text[:80].replace("\n", " | "))

    for entry in radio_entries:
        entry_text = entry.get("text", "")
        if _sender_matches(entry_text, sender_name):
            idx = entry["index"]
            radio = page.locator("input[type='radio']").nth(idx)
            # Click the radio's container — try label first, then parent div
            parent_label = radio.locator("xpath=ancestor::label")
            if await parent_label.count() > 0:
                await parent_label.first.click()
            else:
                parent_div = radio.locator("xpath=ancestor::div").first
                await parent_div.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Selected sender (matched): %s", sender_name)
            return

    raise RuntimeError(
        f"Sender '{sender_name}' not found in address book. "
        f"Saw {len(radio_entries)} entries (check logs for details)."
    )


async def _confirm_sender_info(page: "Page") -> None:
    # 「次へ」を最大2回クリック: アドレス帳選択→依頼主情報確認→発送場所設定
    for step in range(2):
        next_btn = page.get_by_text("次へ", exact=True)
        if await next_btn.count() > 0:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.debug("Sender confirm step %d, URL=%s", step, _safe_url(page.url))
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
    ship_dates = [
        (delivery_dt - timedelta(days=1)).strftime("%Y%m%d"),
        (delivery_dt - timedelta(days=2)).strftime("%Y%m%d"),
        delivery_dt.strftime("%Y%m%d"),
    ]
    logger.info("Will try shipping dates: %s for delivery %s", ship_dates, order.delivery_date)

    date_set = False
    for ship_date in ship_dates:
        option = shipping_select.first.locator(f'option[value="{ship_date}"]')
        if await option.count() == 0:
            logger.debug("Ship date %s not available", ship_date)
            continue

        await shipping_select.first.select_option(value=ship_date)
        await page.wait_for_timeout(TIMEOUT_DROPDOWN_UPDATE_MS)
        logger.info("Selected shipping date: %s", ship_date)

        # 到着日 select の再取得 (発送日変更でオプションが動的更新される)
        delivery_select = page.locator(YAMATO_SELECTORS["delivery_date"])
        if await delivery_select.count() == 0:
            logger.warning("Delivery date select not found after setting ship date")
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
            continue

        await delivery_select.first.select_option(value=order.delivery_date)
        await page.wait_for_timeout(TIMEOUT_DROPDOWN_UPDATE_MS)
        logger.info("Selected delivery date: %s", order.delivery_date)
        date_set = True

        # --- 時間帯の設定 ---
        time_value = order.delivery_time.value if hasattr(order.delivery_time, "value") else str(order.delivery_time)
        if not time_value or time_value == "0":
            logger.info("No delivery time requested; skipping time selection")
            break

        # 時間帯 select の再取得 (到着日変更で時間帯オプションが変わる)
        time_select_all = page.locator("select#timeToReceiveByTZone")
        if await time_select_all.count() > 0:
            time_select = time_select_all.first
        else:
            time_select = page.locator(YAMATO_SELECTORS["delivery_time"]).first

        if await time_select.count() == 0:
            logger.warning("Time select not found")
            break

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
        chosen_time = time_value if target_enabled else next(
            (o["value"] for o in enabled_options
             if not o["disabled"] and o["value"] not in ("0", "")),
            None
        )
        if chosen_time:
            try:
                await time_select.select_option(value=chosen_time, timeout=5000)
            except Exception:
                # JS フォールバック: select_option が効かない場合
                await page.evaluate(f"""() => {{
                    const sel = document.querySelector('#timeToReceiveByTZone')
                        || document.querySelector('select[name="viwb4100ActionBean.timeToReceive"]');
                    if (sel) {{
                        sel.value = '{chosen_time}';
                        sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}""")
            await page.wait_for_timeout(TIMEOUT_INPUT_MS)
            logger.info(
                "Set delivery: ship=%s, deliver=%s, time=%s%s",
                ship_date, order.delivery_date, chosen_time,
                " (fallback)" if chosen_time != time_value else "",
            )
        else:
            logger.warning("No enabled time option found")
        break

    if not date_set:
        logger.warning(
            "Could not set delivery date %s with any shipping date %s",
            order.delivery_date, ship_dates,
        )

    # 「設定する」または「次へ」で確定
    for btn_text in ["設定する", "次へ"]:
        btn = page.get_by_text(btn_text, exact=True)
        if await btn.count() > 0:
            await btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Delivery datetime confirmed with '%s'", btn_text)
            break


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


async def _fill_input(
    page: "Page", selector: str, value: str, timeout_ms: int = TIMEOUT_INPUT_MS
) -> None:
    locator = page.locator(selector)
    if await locator.count() > 0:
        await locator.first.fill(value)
        await locator.first.dispatch_event("input")
        await page.wait_for_timeout(timeout_ms)
