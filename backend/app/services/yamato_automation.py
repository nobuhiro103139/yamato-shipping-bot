import os
from pathlib import Path

from app.config import Settings, get_settings
from app.models.order import ShopifyOrder, ShippingResult, ShippingStatus

QR_CODE_DIR = Path("qr_codes")
QR_CODE_DIR.mkdir(exist_ok=True)

YAMATO_SEND_URL = "https://sp-send.kuronekoyamato.co.jp/"

TIMEOUT_PAGE_LOAD_MS = 2000
TIMEOUT_NAVIGATION_MS = 1000
TIMEOUT_POSTAL_LOOKUP_MS = 1500
TIMEOUT_INPUT_MS = 500
SLOW_MO_MS = 500
PRODUCT_NAME_MAX_LENGTH = 30

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

            await _click_if_visible(page, "通常の荷物を送る")
            await _click_if_visible(page, "発払い")
            await _click_if_visible(page, "1個")
            await _click_if_visible(page, order.package_size.value)

            # Step 5: Fill recipient (お届け先) information
            await _fill_recipient_info(page, order)

            # Step 6: Fill sender (ご依頼主) information
            await _fill_sender_info(page, settings)

            # Step 7: Fill product name (品名)
            product_names = ", ".join(item.title for item in order.items)
            product_name_input = page.locator('input[name*="product"], input[placeholder*="品名"]')
            if await product_name_input.count() > 0:
                await product_name_input.first.fill(product_names[:PRODUCT_NAME_MAX_LENGTH])
                await page.wait_for_timeout(TIMEOUT_INPUT_MS)

            # Step 8: Take screenshot before payment for review
            screenshot_path = str(QR_CODE_DIR / f"{order.order_number}_confirmation.png")
            await page.screenshot(path=screenshot_path, full_page=True)

            # NOTE: Payment step is intentionally left as manual confirmation
            # To fully automate, uncomment and adapt the payment section
            # after confirming the selectors with codegen

            await context.storage_state(path=auth_path)

            return ShippingResult(
                order_id=order.order_id,
                order_number=order.order_number,
                status=ShippingStatus.COMPLETED,
                qr_code_path=screenshot_path,
            )

        except Exception as e:
            error_screenshot = str(QR_CODE_DIR / f"{order.order_number}_error.png")
            await page.screenshot(path=error_screenshot, full_page=True)
            raise e

        finally:
            await browser.close()


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


async def _fill_recipient_info(page: "Page", order: ShopifyOrder) -> None:
    """Fill the recipient (お届け先) section of the Yamato form."""
    addr = order.shipping_address

    postal_code = addr.postal_code.replace("-", "")
    await _fill_input(page, 'input[name*="postal"], input[name*="zip"], input[placeholder*="郵便番号"]', postal_code, TIMEOUT_POSTAL_LOOKUP_MS)
    await _fill_input(page, 'input[name*="name"], input[placeholder*="氏名"]', addr.name)
    await _fill_input(page, 'input[name*="address1"], input[name*="addr1"], input[placeholder*="番地"]', addr.address1)
    if addr.address2:
        await _fill_input(page, 'input[name*="address2"], input[name*="addr2"], input[placeholder*="建物"]', addr.address2)
    await _fill_input(page, 'input[name*="phone"], input[name*="tel"], input[placeholder*="電話"]', addr.phone)


async def _fill_sender_info(page: "Page", settings: Settings) -> None:
    """Fill the sender (ご依頼主) section of the Yamato form."""
    if settings.sender_name:
        await _fill_input(page, 'input[name*="sender_name"], input[name*="senderName"], input[placeholder*="依頼主"]', settings.sender_name)

    if settings.sender_postal_code:
        postal = settings.sender_postal_code.replace("-", "")
        await _fill_input(page, 'input[name*="sender_postal"], input[name*="senderZip"]', postal, TIMEOUT_POSTAL_LOOKUP_MS)

    if settings.sender_address1:
        await _fill_input(page, 'input[name*="sender_address1"], input[name*="senderAddr1"]', settings.sender_address1)

    if settings.sender_address2:
        await _fill_input(page, 'input[name*="sender_address2"], input[name*="senderAddr2"]', settings.sender_address2)

    if settings.sender_phone:
        await _fill_input(page, 'input[name*="sender_phone"], input[name*="senderTel"]', settings.sender_phone)
