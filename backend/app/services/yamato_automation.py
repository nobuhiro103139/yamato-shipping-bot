import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import Settings, get_settings
from app.models.order import PackageSize, ShopifyOrder, ShippingResult, ShippingStatus

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from playwright.async_api import Dialog, Page

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

YAMATO_SEND_URL = "https://sp-send.kuronekoyamato.co.jp/"

TIMEOUT_PAGE_LOAD_MS = 2000
TIMEOUT_NAVIGATION_MS = 1000
TIMEOUT_POSTAL_LOOKUP_MS = 3000
TIMEOUT_INPUT_MS = 500
TIMEOUT_DROPDOWN_UPDATE_MS = 2000
TIMEOUT_DIALOG_MS = 3000
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

PACKAGE_SIZE_LABELS: dict[PackageSize, str] = {
    PackageSize.COMPACT: "コンパクト",
    PackageSize.S: "Ｓ",
    PackageSize.M: "Ｍ",
    PackageSize.L: "Ｌ",
    PackageSize.LL: "ＬＬ",
}

YAMATO_SELECTORS = {
    "size_radio": 'input[name="viwb2050ActionBean.size"]',
    "item_name": 'input[name="viwb2050ActionBean.itemName"]',
    "handling_checkbox": 'input[name="handling"]',
    "not_prohibited": 'input[name="viwb2050ActionBean.notProhibited"]',
    "next_baggage": 'a[data-action="Viwb2050Action_doNext.action"]',
    "recipient_last_name": 'input[name="viwb3040ActionBean.lastName"]',
    "recipient_first_name": 'input[name="viwb3040ActionBean.firstName"]',
    "recipient_zip": 'input[name="viwb3040ActionBean.zipCode"]',
    "address_search_btn": "button#btnSearch",
    "recipient_address1": 'input[name="viwb3040ActionBean.address1"]',
    "recipient_address2": 'textarea[name="viwb3040ActionBean.address2"]',
    "recipient_address3": 'input[name="viwb3040ActionBean.address3"]',
    "recipient_address3opt": 'input[name="viwb3040ActionBean.address3opt"]',
    "recipient_address4": 'input[name="viwb3040ActionBean.address4"]',
    "recipient_company": 'input[name="viwb3040ActionBean.companyName"]',
    "recipient_phone": 'input[name="viwb3040ActionBean.phoneNumber"]',
    "next_recipient": "a#next",
    "sender_last_name": 'input[name="viwb3130ActionBean.lastName"]',
    "sender_first_name": 'input[name="viwb3130ActionBean.firstName"]',
    "sender_zip": 'input[name="viwb3130ActionBean.zipCode"]',
    "sender_address_search_btn": "button#btnSearch",
    "sender_address3": 'input[name="viwb3130ActionBean.address3"]',
    "sender_address3opt": 'input[name="viwb3130ActionBean.address3opt"]',
    "sender_address4": 'input[name="viwb3130ActionBean.address4"]',
    "sender_phone": 'input[name="viwb3130ActionBean.phoneNumber"]',
    "shipping_date": 'select[name="viwb4100ActionBean.dateToShip"]',
    "delivery_date": 'select[name="viwb4100ActionBean.dateToReceive"]',
    "delivery_time": 'select[name="viwb4100ActionBean.timeToReceive"]',
}


async def save_auth_state() -> dict[str, object]:
    """Launch browser in headful mode for manual Kuroneko Members login.

    Opens a visible browser window navigated to the Yamato send page.
    The user should log in manually, then call /api/yamato/save-session
    to persist the session state.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "success": False,
            "message": "Playwright is not installed. Run: poetry add playwright && playwright install chromium",
        }

    settings = get_settings()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(**DEVICE_CONFIG)
        page = await context.new_page()
        await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded")

        return {
            "success": True,
            "message": (
                "Browser launched. Please log in to Kuroneko Members manually. "
                "Once logged in, call the /api/yamato/save-session endpoint."
            ),
            "note": "This endpoint opens a visible browser for manual login.",
        }


async def process_shipment(order: ShopifyOrder) -> ShippingResult:
    """Automate the Yamato 'Send via Smartphone' flow for a single order.

    Launches Playwright with mobile emulation, loads saved auth state,
    and fills out the shipment form for the given order.
    """
    settings = get_settings()
    auth_path = settings.auth_state_path

    if not os.path.exists(auth_path):
        return ShippingResult(
            order_id=order.order_id,
            order_number=order.order_number,
            status=ShippingStatus.FAILED,
            error_message="Auth state not found. Please run initial login first.",
        )

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return ShippingResult(
            order_id=order.order_id,
            order_number=order.order_number,
            status=ShippingStatus.FAILED,
            error_message="Playwright is not installed.",
        )

    try:
        result = await _run_yamato_automation(order, settings, auth_path)
        return result
    except Exception as e:
        return ShippingResult(
            order_id=order.order_id,
            order_number=order.order_number,
            status=ShippingStatus.FAILED,
            error_message=str(e),
        )


async def _run_yamato_automation(
    order: ShopifyOrder, settings: Settings, auth_path: str
) -> ShippingResult:
    """Run the full Yamato form automation flow inside a Playwright browser."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=settings.headless_browser,
            slow_mo=SLOW_MO_MS,
        )
        context = await browser.new_context(
            **DEVICE_CONFIG,
            storage_state=auth_path,
        )
        page = await context.new_page()
        async def _handle_dialog(dialog: "Dialog") -> None:
            logger.info("Dialog [%s]: %s", dialog.type, dialog.message)
            await dialog.accept()

        page.on("dialog", _handle_dialog)

        try:
            await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(TIMEOUT_PAGE_LOAD_MS)

            await _navigate_to_package_settings(page)
            await _fill_package_settings(page, order)
            await page.wait_for_timeout(TIMEOUT_DIALOG_MS)

            await _select_direct_address_input(page)
            await _fill_recipient_info(page, order)

            await _select_sender_from_address_book(page, settings)
            await _confirm_sender_info(page)

            await _select_shipping_location(page)
            await _fill_delivery_datetime(page, order)

            await _save_draft(page)

            screenshot_path = str(RESULTS_DIR / f"{order.order_number}_confirmation.png")
            await page.screenshot(path=screenshot_path, full_page=True)
            await context.storage_state(path=auth_path)

            return ShippingResult(
                order_id=order.order_id,
                order_number=order.order_number,
                status=ShippingStatus.COMPLETED,
                qr_code_path=screenshot_path,
            )

        except Exception:
            error_screenshot = str(RESULTS_DIR / f"{order.order_number}_error.png")
            await page.screenshot(path=error_screenshot, full_page=True)
            raise

        finally:
            await browser.close()


async def _navigate_to_package_settings(page: "Page") -> None:
    """Navigate from the top page through service/payment/count selection."""
    await _click_if_visible(page, "通常の荷物を送る", required=True)
    await _click_if_visible(page, "発払い", required=True)
    await _click_if_visible(page, "１個", required=True)


async def _fill_package_settings(page: "Page", order: ShopifyOrder) -> None:
    """Fill the package settings form (size, product name, handling, confirmation)."""
    size_label = PACKAGE_SIZE_LABELS.get(order.package_size)
    if size_label:
        size_span = page.get_by_text(size_label, exact=True)
        if await size_span.count() > 0:
            await size_span.first.click()
            await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    product_names = ", ".join(item.title for item in order.items)
    item_name_input = page.locator(YAMATO_SELECTORS["item_name"])
    if await item_name_input.count() > 0:
        await item_name_input.first.fill(product_names[:PRODUCT_NAME_MAX_LENGTH])
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    handling_01 = page.locator(f'{YAMATO_SELECTORS["handling_checkbox"]}[value="01"]')
    if await handling_01.count() > 0:
        is_checked = await handling_01.first.is_checked()
        if not is_checked:
            await handling_01.first.evaluate(
                "el => el.parentElement.querySelector('span').click()"
            )
            await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    not_prohibited = page.locator(YAMATO_SELECTORS["not_prohibited"])
    if await not_prohibited.count() > 0:
        is_checked = await not_prohibited.first.is_checked()
        if not is_checked:
            await not_prohibited.first.evaluate("el => el.parentElement.click()")
            await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    next_btn = page.locator(YAMATO_SELECTORS["next_baggage"])
    if await next_btn.count() > 0:
        await next_btn.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)


async def _select_direct_address_input(page: "Page") -> None:
    """Select 'Enter address directly' on the delivery method page."""
    await _click_if_visible(page, "直接住所を入力する", required=True)


async def _fill_recipient_info(page: "Page", order: ShopifyOrder) -> None:
    """Fill the recipient form including notification and address book settings."""
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

    next_btn = page.locator(YAMATO_SELECTORS["next_recipient"])
    await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    if await next_btn.count() > 0:
        is_disabled = await next_btn.first.get_attribute("disabled")
        if not is_disabled:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)


async def _toggle_notification(page: "Page", email: str) -> None:
    """Check the delivery notification checkbox and fill the email field."""
    notify_label = page.get_by_text("お届け予定をお知らせ")
    if await notify_label.count() > 0:
        checkbox = notify_label.locator("xpath=ancestor::label//input[@type='checkbox']")
        if await checkbox.count() == 0:
            checkbox = notify_label.locator("xpath=preceding-sibling::input[@type='checkbox'] | following-sibling::input[@type='checkbox']")
        if await checkbox.count() > 0:
            if not await checkbox.first.is_checked():
                await notify_label.first.click()
                await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    email_input = page.locator('input[type="email"]')
    if await email_input.count() == 0:
        email_input = page.locator('input[name*="mail" i]')
    if await email_input.count() > 0:
        await email_input.first.fill(email)
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)


async def _uncheck_address_book(page: "Page") -> None:
    """Uncheck the address book registration checkbox."""
    address_book_label = page.get_by_text("アドレス帳へ登録")
    if await address_book_label.count() > 0:
        checkbox = address_book_label.locator("xpath=ancestor::label//input[@type='checkbox']")
        if await checkbox.count() > 0:
            if await checkbox.first.is_checked():
                await address_book_label.first.click()
                await page.wait_for_timeout(TIMEOUT_INPUT_MS)


async def _select_sender_from_address_book(page: "Page", settings: Settings) -> None:
    """Select sender from address book instead of manual input."""
    await _click_if_visible(page, "アドレス帳から選択", required=False)
    await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)

    sender_name = settings.sender_name or "フツテック"
    sender_entry = page.get_by_text(sender_name, exact=False)
    if await sender_entry.count() > 0:
        await sender_entry.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    else:
        logger.warning("Exact sender '%s' not found; attempting partial match", sender_name)
        parts = sender_name.split()
        for part in parts:
            entry = page.get_by_text(part, exact=False)
            match_count = await entry.count()
            if match_count == 1:
                logger.warning("Selected sender via partial match on '%s'", part)
                await entry.first.click()
                await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
                break
            elif match_count > 1:
                logger.warning("Partial match '%s' is ambiguous (%d results), skipping", part, match_count)
        else:
            logger.error("Failed to select sender '%s' from address book - no match found", sender_name)


async def _confirm_sender_info(page: "Page") -> None:
    """Click next on the pre-filled sender info page."""
    next_btn = page.locator("a#next")
    if await next_btn.count() > 0:
        is_disabled = await next_btn.first.get_attribute("disabled")
        if not is_disabled:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)


async def _select_shipping_location(page: "Page") -> None:
    """Select shipping location as nearest to sender address."""
    await _click_if_visible(page, "近くから発送", required=False)
    if await page.get_by_text("近くから発送").count() == 0:
        await _click_if_visible(page, "ご依頼主住所", required=False)


async def _fill_delivery_datetime(page: "Page", order: ShopifyOrder) -> None:
    """Set shipping date, delivery date, and time slot with fallback logic."""
    if not order.delivery_date:
        next_btn = page.locator("a#next")
        if await next_btn.count() > 0:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
        return

    try:
        delivery_dt = datetime.strptime(order.delivery_date, "%Y%m%d")
    except ValueError:
        logger.exception("Invalid delivery_date format '%s' for order %s", order.delivery_date, order.order_number)
        next_btn = page.locator("a#next")
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

    next_btn = page.locator("a#next")
    if await next_btn.count() > 0:
        is_disabled = await next_btn.first.get_attribute("disabled")
        if not is_disabled:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)


async def _save_draft(page: "Page") -> None:
    """Save the shipment as a draft on the confirmation page."""
    btn = page.get_by_text("保存して別の荷物を送る")
    if await btn.count() > 0:
        await btn.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    else:
        logger.warning("Save draft button not found - draft may not be saved")
    await page.wait_for_timeout(TIMEOUT_DIALOG_MS)


async def _click_if_visible(page: "Page", text: str, *, required: bool = False) -> None:
    """Click the first element matching *text* if it exists on the page."""
    btn = page.get_by_text(text)
    if await btn.count() > 0:
        await btn.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    elif required:
        raise RuntimeError(f"Required button not found: '{text}'")


async def _fill_input(page: "Page", selector: str, value: str, timeout_ms: int = TIMEOUT_INPUT_MS) -> None:
    """Fill the first input matching *selector* with *value* if it exists."""
    locator = page.locator(selector)
    if await locator.count() > 0:
        await locator.first.fill(value)
        await page.wait_for_timeout(timeout_ms)
