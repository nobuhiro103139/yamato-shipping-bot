import os
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import Settings, get_settings
from app.models.order import ShopifyOrder, ShippingResult, ShippingStatus

if TYPE_CHECKING:
    from playwright.async_api import Page

QR_CODE_DIR = Path("qr_codes")
QR_CODE_DIR.mkdir(exist_ok=True)

YAMATO_SEND_URL = "https://sp-send.kuronekoyamato.co.jp/"

TIMEOUT_PAGE_LOAD_MS = 2000
TIMEOUT_NAVIGATION_MS = 1000
TIMEOUT_POSTAL_LOOKUP_MS = 3000
TIMEOUT_INPUT_MS = 500
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

        try:
            await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(TIMEOUT_PAGE_LOAD_MS)

            await _navigate_to_package_settings(page)

            await _fill_package_settings(page, order)

            await _select_direct_address_input(page)

            await _fill_recipient_info(page, order)

            await _fill_sender_info(page, settings)

            screenshot_path = str(QR_CODE_DIR / f"{order.order_number}_confirmation.png")
            await page.screenshot(path=screenshot_path, full_page=True)

            await context.storage_state(path=auth_path)

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


async def _navigate_to_package_settings(page: "Page") -> None:
    """Navigate from the top page through service/payment/count selection."""
    await _click_if_visible(page, "通常の荷物を送る")
    await _click_if_visible(page, "発払い")
    await _click_if_visible(page, "１個")


async def _fill_package_settings(page: "Page", order: ShopifyOrder) -> None:
    """Fill the package settings form (size, product name, handling, confirmation)."""
    size_value = order.package_size.value
    size_radio = page.locator(f'{YAMATO_SELECTORS["size_radio"]}[value="{size_value}"]')
    if await size_radio.count() > 0:
        await size_radio.first.evaluate("el => el.parentElement.querySelector('span').click()")
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    product_names = ", ".join(item.title for item in order.items)
    item_name_input = page.locator(YAMATO_SELECTORS["item_name"])
    if await item_name_input.count() > 0:
        await item_name_input.first.fill(product_names[:PRODUCT_NAME_MAX_LENGTH])
        await page.wait_for_timeout(TIMEOUT_INPUT_MS)

    handling_01 = page.locator(f'{YAMATO_SELECTORS["handling_checkbox"]}[value="01"]')
    if await handling_01.count() > 0:
        await handling_01.first.evaluate("el => el.parentElement.querySelector('span').click()")
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
    await _click_if_visible(page, "直接住所を入力する")


async def _fill_recipient_info(page: "Page", order: ShopifyOrder) -> None:
    """Fill the recipient form on the Yamato Viwb3040 page."""
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

    await _fill_input(page, YAMATO_SELECTORS["recipient_address3"], addr.address1)

    if addr.address2:
        await _fill_input(page, YAMATO_SELECTORS["recipient_address4"], addr.address2)

    phone = addr.phone.replace("-", "")
    if phone:
        await _fill_input(page, YAMATO_SELECTORS["recipient_phone"], phone)

    next_btn = page.locator(YAMATO_SELECTORS["next_recipient"])
    await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)
    if await next_btn.count() > 0:
        is_disabled = await next_btn.first.get_attribute("disabled")
        if not is_disabled:
            await next_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)


async def _fill_sender_info(page: "Page", settings: Settings) -> None:
    """Fill the sender form if the page is displayed."""
    if settings.sender_name:
        parts = settings.sender_name.split(maxsplit=1)
        sender_last = parts[0]
        sender_first = parts[1] if len(parts) > 1 else ""
        await _fill_input(page, YAMATO_SELECTORS["sender_last_name"], sender_last)
        if sender_first:
            await _fill_input(page, YAMATO_SELECTORS["sender_first_name"], sender_first)

    if settings.sender_postal_code:
        postal = settings.sender_postal_code.replace("-", "")
        await _fill_input(page, YAMATO_SELECTORS["sender_zip"], postal)

        search_btn = page.locator(YAMATO_SELECTORS["sender_address_search_btn"])
        if await search_btn.count() > 0:
            await search_btn.first.click()
            await page.wait_for_timeout(TIMEOUT_POSTAL_LOOKUP_MS)

    if settings.sender_address1:
        await _fill_input(page, YAMATO_SELECTORS["sender_address3"], settings.sender_address1)

    if settings.sender_address2:
        await _fill_input(page, YAMATO_SELECTORS["sender_address4"], settings.sender_address2)

    if settings.sender_phone:
        phone = settings.sender_phone.replace("-", "")
        await _fill_input(page, YAMATO_SELECTORS["sender_phone"], phone)


async def _click_if_visible(page: "Page", text: str) -> None:
    """Click the first element matching *text* if it exists on the page."""
    btn = page.get_by_text(text)
    if await btn.count() > 0:
        await btn.first.click()
        await page.wait_for_timeout(TIMEOUT_NAVIGATION_MS)


async def _fill_input(page: "Page", selector: str, value: str, timeout_ms: int = TIMEOUT_INPUT_MS) -> None:
    """Fill the first input matching *selector* with *value* if it exists."""
    locator = page.locator(selector)
    if await locator.count() > 0:
        await locator.first.fill(value)
        await page.wait_for_timeout(timeout_ms)
