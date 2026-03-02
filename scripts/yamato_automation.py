import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

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
            logger.info("STEP: login done, URL=%s", page.url)

            await _navigate_to_package_settings(page, order)
            logger.info("STEP: navigate_to_package_settings done, URL=%s", page.url)

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
        logger.warning("Expected login page, got: %s", page.url)
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


async def _fill_package_settings(page: "Page", order: RentalOrder) -> None:
    radio_value = PACKAGE_SIZE_TO_RADIO_VALUE.get(order.package_size, "S")
    await page.evaluate(
        """(targetValue) => {
            const radios = document.querySelectorAll('input[name="viwb2050ActionBean.size"]');
            for (const r of radios) {
                if (r.value === targetValue) {
                    r.checked = true;
                    r.dispatchEvent(new Event('change', {bubbles: true}));
                    const lbl = r.closest('label');
                    if (lbl) lbl.click();
                    return;
                }
            }
        }""",
        radio_value,
    )
    await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    product_names = ", ".join(item.title for item in order.items)
    item_name_input = page.locator(YAMATO_SELECTORS["item_name"])
    if await item_name_input.count() > 0:
        await item_name_input.first.fill(product_names[:PRODUCT_NAME_MAX_LENGTH])
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    # 精密機械チェック - ラベルを直接クリック
    handling_label = page.get_by_text("精密機械", exact=False)
    if await handling_label.count() > 0:
        handling_cb = page.locator('input[name="handling"][value="01"]')
        if await handling_cb.count() > 0 and not await handling_cb.first.is_checked():
            await handling_label.first.click()
            logger.info("Clicked 精密機械 label")
    await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    # 宅急便で送れないものに該当しません チェック
    prohibited_label = page.get_by_text("宅急便で送れないものに該当しません", exact=False)
    if await prohibited_label.count() > 0:
        prohibited_cb = page.locator('input[name="viwb2050ActionBean.notProhibited"]')
        if await prohibited_cb.count() > 0 and not await prohibited_cb.first.is_checked():
            await prohibited_label.first.click()
            logger.info("Clicked 宅急便で送れないもの label")
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
    if await ok_btn.count() > 0:
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

    await _fill_input(page, YAMATO_SELECTORS["recipient_last_name"], addr.last_name)
    if addr.first_name:
        await _fill_input(page, YAMATO_SELECTORS["recipient_first_name"], addr.first_name)

    postal_code = addr.postal_code.replace("-", "")
    await _fill_input(page, YAMATO_SELECTORS["recipient_zip"], postal_code)

    search_btn = page.locator(YAMATO_SELECTORS["address_search_btn"])
    if await search_btn.count() > 0:
        await search_btn.first.click()
        await page.wait_for_timeout(5000)  # ポップアップ表示を十分待つ

    # 丁目選択ポップアップの処理
    chome_to_select = addr.chome
    banchi_value = addr.banchi
    go_value = addr.go
    address_for_field = addr.address1

    # chome が空の場合、address1 から丁目・番地・号を解析
    if not chome_to_select and addr.address1:
        match = re.search(r"(\d+)-(\d+)(?:-(\d+))?$", addr.address1)
        if match:
            chome_to_select = match.group(1)
            banchi_value = match.group(2)
            go_value = match.group(3) or ""
            address_for_field = ""
            logger.info(
                "Parsed address: chome=%s, banchi=%s, go=%s",
                chome_to_select, banchi_value, go_value,
            )

    # 丁目選択: iframe 内のポップアップで全角数字を使う
    if chome_to_select:
        # 半角→全角変換 (Yamato uses full-width numbers: １丁目, ２丁目, etc.)
        fullwidth_chome = chome_to_select.translate(
            str.maketrans("0123456789", "０１２３４５６７８９")
        )
        target_text = f"{fullwidth_chome}丁目"
        # 半角版もフォールバック用に用意
        target_text_half = f"{chome_to_select}丁目"
        chome_clicked = False

        # iframe を検索 (chome popup は常に iframe 内)
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                frame_text = await frame.locator("body").inner_text(timeout=2000)
                if "丁目" not in frame_text:
                    continue
                for txt in [target_text, target_text_half]:
                    for loc in [
                        frame.get_by_text(txt, exact=True),
                        frame.get_by_role("link", name=txt),
                        frame.locator(f"a:has-text('{txt}')"),
                    ]:
                        try:
                            if await loc.count() > 0:
                                await loc.first.click()
                                await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                                logger.info("Selected chome: %s", txt)
                                chome_clicked = True
                                break
                        except Exception:
                            continue
                    if chome_clicked:
                        break
                if chome_clicked:
                    break
            except Exception:
                continue

        if not chome_clicked:
            logger.warning("Could not find chome option: %s", target_text)

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
                    return {index: i, text: p.innerText.substring(0, 200)};
                p = p.parentElement;
            }
            return {index: i, text: ''};
        });
    }""")

    for entry in radio_entries:
        if sender_name in entry.get("text", ""):
            idx = entry["index"]
            parent_div = page.locator("input[type='radio']").nth(idx).locator("xpath=ancestor::div").first
            await parent_div.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Selected sender: %s", sender_name)
            return

    raise RuntimeError(
        f"Sender '{sender_name}' not found in address book"
    )


async def _confirm_sender_info(page: "Page") -> None:
    # 「次へ」を最大2回クリック: アドレス帳選択→依頼主情報確認→発送場所設定
    for step in range(2):
        next_btn = page.get_by_text("次へ", exact=True)
        if await next_btn.count() > 0:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.debug("Sender confirm step %d, URL=%s", step, page.url)
        else:
            break


async def _select_shipping_location(page: "Page", settings: Settings) -> None:
    preferred = settings.preferred_shipping_location
    candidates = []
    if preferred:
        candidates.append(preferred)
    candidates.append("近くから発送")

    for loc_text in candidates:
        loc = page.get_by_text(loc_text, exact=False)
        if await loc.count() > 0:
            await loc.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Selected shipping location: %s", loc_text)
            break
    else:
        logger.warning("No shipping location found")

    # 「次へ」ボタンで進む
    next_btn = page.get_by_text("次へ", exact=True)
    if await next_btn.count() > 0:
        await next_btn.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
        logger.debug("Shipping location next, URL=%s", page.url)


async def _fill_delivery_datetime(page: "Page", order: RentalOrder) -> None:
    if not order.delivery_date:
        return

    try:
        delivery_dt = datetime.strptime(order.delivery_date, "%Y%m%d")
    except ValueError:
        logger.warning("Invalid delivery_date: %s", order.delivery_date)
        return

    # 確認ページの場合、id="warning" の変更ボタン (お届け予定日) をクリック
    shipping_select = page.locator(YAMATO_SELECTORS["shipping_date"])
    if await shipping_select.count() == 0:
        # お届け予定日の変更ボタン (Viwb4080Action_doDeliveryPreferredDate)
        delivery_change = page.locator("button#warning")
        if await delivery_change.count() > 0:
            await delivery_change.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Clicked 変更 for お届け予定日")

            # モーダルが出た場合 OK をクリック
            ok_btn = page.get_by_text("OK", exact=True)
            if await ok_btn.count() > 0 and await ok_btn.last.is_visible():
                await ok_btn.last.click()
                await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                logger.debug("Confirmed delivery date change modal, URL=%s", page.url)

        shipping_select = page.locator(YAMATO_SELECTORS["shipping_date"])

    if await shipping_select.count() == 0:
        logger.warning("Delivery date selects not found")
        return

    delivery_select = page.locator(YAMATO_SELECTORS["delivery_date"])
    # 時間帯 select は複数あるので、有効な(disabled でない)ものを使う
    time_select = page.locator("select#timeToReceiveByTZone")
    if await time_select.count() == 0:
        time_select = page.locator(YAMATO_SELECTORS["delivery_time"]).first

    ship_dates = [
        (delivery_dt - timedelta(days=1)).strftime("%Y%m%d"),
        (delivery_dt - timedelta(days=2)).strftime("%Y%m%d"),
        delivery_dt.strftime("%Y%m%d"),
    ]

    for ship_date in ship_dates:
        if await shipping_select.count() == 0:
            break
        option = shipping_select.first.locator(f'option[value="{ship_date}"]')
        if await option.count() > 0:
            await shipping_select.first.select_option(value=ship_date)
            await page.wait_for_timeout(TIMEOUT_DROPDOWN_UPDATE_MS)

            if await delivery_select.count() > 0:
                delivery_option = delivery_select.first.locator(
                    f'option[value="{order.delivery_date}"]'
                )
                if await delivery_option.count() > 0:
                    await delivery_select.first.select_option(value=order.delivery_date)
                    await page.wait_for_timeout(TIMEOUT_DROPDOWN_UPDATE_MS)

                    time_value = order.delivery_time.value if hasattr(order.delivery_time, 'value') else str(order.delivery_time)
                    if time_value and time_value != "0" and await time_select.count() > 0:
                        # 時間帯 select の有効なオプションを確認
                        enabled_options = await time_select.evaluate("""el => {
                            return Array.from(el.options).map(o => ({
                                value: o.value, text: o.text, disabled: o.disabled
                            }));
                        }""")
                        logger.debug("Time options: %s", enabled_options)

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
                            # Playwright の select_option が失敗する場合があるので JS で直接設定
                            try:
                                await time_select.select_option(value=chosen_time, timeout=5000)
                            except Exception:
                                await page.evaluate(f"""() => {{
                                    const sel = document.querySelector('#timeToReceiveByTZone');
                                    if (sel) {{
                                        sel.value = '{chosen_time}';
                                        sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                                    }}
                                }}""")
                            await page.wait_for_timeout(TIMEOUT_INPUT_MS)
                            logger.info("Set delivery: ship=%s, deliver=%s, time=%s%s",
                                        ship_date, order.delivery_date, chosen_time,
                                        " (fallback)" if chosen_time != time_value else "")
                        break
                    else:
                        logger.info("Set delivery: ship=%s, deliver=%s (no time)", ship_date, order.delivery_date)
                        break

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
