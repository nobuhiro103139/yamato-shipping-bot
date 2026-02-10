import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from scripts.config import Settings, get_settings
from scripts.models import PackageSize, ShopifyOrder, ShippingResult, ShippingStatus

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


async def process_shipment(order: ShopifyOrder) -> ShippingResult:
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
    order: ShopifyOrder, settings: Settings
) -> ShippingResult:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
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
            await _navigate_to_package_settings(page, order)
            await _fill_package_settings(page, order)

            await _select_direct_address_input(page)
            await _fill_recipient_info(page, order)

            await _select_sender_from_address_book(page, settings)
            await _confirm_sender_info(page)

            await _select_shipping_location(page)
            await _fill_delivery_datetime(page, order)

            await _save_draft(page)

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

    if "auth.kms" not in page.url:
        logger.warning("Expected auth.kms page, got: %s", page.url)
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
            if "auth.kms" in page.url:
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


async def _navigate_to_package_settings(page: "Page", order: ShopifyOrder) -> None:
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


async def _fill_package_settings(page: "Page", order: ShopifyOrder) -> None:
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

    await page.evaluate("""() => {
        const cb = document.querySelector('input[name="handling"][value="01"]');
        if (cb && !cb.checked) {
            cb.checked = true;
            cb.dispatchEvent(new Event('change', {bubbles: true}));
            const lbl = cb.closest('label');
            if (lbl) lbl.click();
        }
    }""")
    await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    await page.evaluate("""() => {
        const cb = document.querySelector('input[name="viwb2050ActionBean.notProhibited"]');
        if (cb && !cb.checked) {
            cb.checked = true;
            cb.dispatchEvent(new Event('change', {bubbles: true}));
            const lbl = cb.closest('label');
            if (lbl) lbl.click();
        }
    }""")
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


async def _select_direct_address_input(page: "Page") -> None:
    direct = page.get_by_text("直接住所を入力する", exact=False)
    if await direct.count() > 0:
        await direct.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)


async def _fill_recipient_info(page: "Page", order: ShopifyOrder) -> None:
    addr = order.shipping_address

    await _fill_input(page, YAMATO_SELECTORS["recipient_last_name"], addr.last_name)
    if addr.first_name:
        await _fill_input(page, YAMATO_SELECTORS["recipient_first_name"], addr.first_name)

    postal_code = addr.postal_code.replace("-", "")
    await _fill_input(page, YAMATO_SELECTORS["recipient_zip"], postal_code)

    search_btn = page.locator(YAMATO_SELECTORS["address_search_btn"])
    if await search_btn.count() > 0:
        await search_btn.first.click()
        await page.wait_for_timeout(TIMEOUT_POSTAL_LOOKUP_MS)

    if addr.chome:
        chome_option = page.get_by_text(f"{addr.chome}丁目")
        if await chome_option.count() > 0:
            await chome_option.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)

    if addr.banchi:
        await _fill_input(page, YAMATO_SELECTORS["recipient_address3"], addr.banchi)
    elif addr.address1:
        await _fill_input(page, YAMATO_SELECTORS["recipient_address3"], addr.address1)

    if addr.go:
        await _fill_input(page, YAMATO_SELECTORS["recipient_address3opt"], addr.go)

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


async def _toggle_notification(page: "Page", email: str) -> None:
    notify_cb = page.locator('input[name*="notifyFlg"]')
    if await notify_cb.count() > 0:
        if not await notify_cb.first.is_checked():
            await page.evaluate("""() => {
                const cb = document.querySelector('input[name*="notifyFlg"]');
                if (cb) {
                    cb.checked = true;
                    cb.dispatchEvent(new Event('change', {bubbles: true}));
                    const lbl = cb.closest('label');
                    if (lbl) lbl.click();
                }
            }""")
            await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    email_input = page.locator('input[name*="mailAddress"]')
    if await email_input.count() == 0:
        email_input = page.locator('input[type="email"]')
    if await email_input.count() > 0:
        await email_input.first.fill(email)
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)


async def _uncheck_address_book(page: "Page") -> None:
    await page.evaluate("""() => {
        const cb = document.querySelector('input[name*="addAddressBook"]');
        if (cb && cb.checked) {
            cb.checked = false;
            cb.dispatchEvent(new Event('change', {bubbles: true}));
            const lbl = cb.closest('label');
            if (lbl) lbl.click();
        }
    }""")
    await page.wait_for_timeout(TIMEOUT_INPUT_MS)


async def _select_sender_from_address_book(
    page: "Page", settings: Settings
) -> None:
    addr_book = page.get_by_text("アドレス帳から選択", exact=False)
    if await addr_book.count() > 0:
        await addr_book.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)

    sender_name = settings.sender_name or "フツテック"
    for candidate in [sender_name, "フツテック", "TechRental"]:
        entry = page.get_by_text(candidate, exact=False)
        if await entry.count() > 0:
            await entry.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            logger.info("Selected sender: %s", candidate)
            return

    raise RuntimeError(
        f"Sender '{sender_name}' not found in address book"
    )


async def _confirm_sender_info(page: "Page") -> None:
    next_btn = page.locator(YAMATO_SELECTORS["next_btn"])
    if await next_btn.count() > 0:
        is_disabled = await next_btn.first.get_attribute("disabled")
        if not is_disabled:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)


async def _select_shipping_location(page: "Page") -> None:
    for loc_text in ["近くから発送", "コンビニから発送", "ご依頼主住所"]:
        loc = page.get_by_text(loc_text, exact=False)
        if await loc.count() > 0:
            await loc.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
            return


async def _fill_delivery_datetime(page: "Page", order: ShopifyOrder) -> None:
    if not order.delivery_date:
        next_btn = page.locator(YAMATO_SELECTORS["next_btn"])
        if await next_btn.count() > 0:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
        return

    try:
        delivery_dt = datetime.strptime(order.delivery_date, "%Y%m%d")
    except ValueError:
        logger.exception(
            "Invalid delivery_date format '%s' for order %s",
            order.delivery_date,
            order.order_number,
        )
        next_btn = page.locator(YAMATO_SELECTORS["next_btn"])
        if await next_btn.count() > 0:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
        return

    ship_dates = [
        (delivery_dt - timedelta(days=1)).strftime("%Y%m%d"),
        (delivery_dt - timedelta(days=2)).strftime("%Y%m%d"),
    ]

    shipping_select = page.locator(YAMATO_SELECTORS["shipping_date"])
    delivery_select = page.locator(YAMATO_SELECTORS["delivery_date"])
    time_select = page.locator(YAMATO_SELECTORS["delivery_time"])

    for ship_date in ship_dates:
        option = shipping_select.locator(f'option[value="{ship_date}"]')
        if await option.count() > 0:
            await shipping_select.select_option(value=ship_date)
            await page.wait_for_timeout(TIMEOUT_DROPDOWN_UPDATE_MS)

            delivery_option = delivery_select.locator(
                f'option[value="{order.delivery_date}"]'
            )
            if await delivery_option.count() > 0:
                await delivery_select.select_option(value=order.delivery_date)
                await page.wait_for_timeout(TIMEOUT_DROPDOWN_UPDATE_MS)

                if order.delivery_time and order.delivery_time != "0":
                    time_option = time_select.locator(
                        f'option[value="{order.delivery_time}"]'
                    )
                    if await time_option.count() > 0:
                        await time_select.select_option(value=order.delivery_time)
                        await page.wait_for_timeout(TIMEOUT_INPUT_MS)
                        break
                    else:
                        continue
                else:
                    break

    next_btn = page.locator(YAMATO_SELECTORS["next_btn"])
    if await next_btn.count() > 0:
        is_disabled = await next_btn.first.get_attribute("disabled")
        if not is_disabled:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)


async def _save_draft(page: "Page") -> None:
    btn = page.get_by_text("保存して別の荷物を送る")
    if await btn.count() > 0:
        await btn.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    else:
        logger.warning("Save draft button not found - draft may not be saved")
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
