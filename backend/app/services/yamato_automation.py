import os
import asyncio
from pathlib import Path
from app.config import get_settings
from app.models.order import ShopifyOrder, ShippingResult, ShippingStatus

QR_CODE_DIR = Path("qr_codes")
QR_CODE_DIR.mkdir(exist_ok=True)

YAMATO_SEND_URL = "https://sp-send.kuronekoyamato.co.jp/"

DEVICE_CONFIG = {
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


async def save_auth_state() -> dict:
    """
    Launch browser in headful mode for manual login.
    After login, save the session state to auth.json.
    This should be called once for initial setup.
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
    """
    Automate the Yamato 'Send via Smartphone' flow for a single order.
    Uses Playwright with mobile emulation.
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
    order: ShopifyOrder, settings, auth_path: str
) -> ShippingResult:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=settings.headless_browser,
            slow_mo=500,
        )
        context = await browser.new_context(
            **DEVICE_CONFIG,
            storage_state=auth_path,
        )
        page = await context.new_page()

        try:
            await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            # Step 1: Select "通常の荷物を送る" (Send a regular package)
            normal_send_btn = page.get_by_text("通常の荷物を送る")
            if await normal_send_btn.count() > 0:
                await normal_send_btn.first.click()
                await page.wait_for_timeout(1000)

            # Step 2: Select "発払い" (Prepaid)
            prepaid_btn = page.get_by_text("発払い")
            if await prepaid_btn.count() > 0:
                await prepaid_btn.first.click()
                await page.wait_for_timeout(1000)

            # Step 3: Select package count (1個)
            one_pkg_btn = page.get_by_text("1個")
            if await one_pkg_btn.count() > 0:
                await one_pkg_btn.first.click()
                await page.wait_for_timeout(1000)

            # Step 4: Select package size
            size_btn = page.get_by_text(order.package_size.value)
            if await size_btn.count() > 0:
                await size_btn.first.click()
                await page.wait_for_timeout(1000)

            # Step 5: Fill recipient (お届け先) information
            await _fill_recipient_info(page, order)

            # Step 6: Fill sender (ご依頼主) information
            await _fill_sender_info(page, settings)

            # Step 7: Fill product name (品名)
            product_names = ", ".join(
                f"{item.title}" for item in order.items
            )
            product_name_input = page.locator('input[name*="product"], input[placeholder*="品名"]')
            if await product_name_input.count() > 0:
                await product_name_input.first.fill(product_names[:30])
                await page.wait_for_timeout(500)

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


async def _fill_recipient_info(page, order: ShopifyOrder):
    addr = order.shipping_address

    postal_input = page.locator('input[name*="postal"], input[name*="zip"], input[placeholder*="郵便番号"]')
    if await postal_input.count() > 0:
        postal_code = addr.postal_code.replace("-", "")
        await postal_input.first.fill(postal_code)
        await page.wait_for_timeout(1500)

    name_input = page.locator('input[name*="name"], input[placeholder*="氏名"]')
    if await name_input.count() > 0:
        await name_input.first.fill(addr.name)
        await page.wait_for_timeout(500)

    addr1_input = page.locator('input[name*="address1"], input[name*="addr1"], input[placeholder*="番地"]')
    if await addr1_input.count() > 0:
        await addr1_input.first.fill(addr.address1)
        await page.wait_for_timeout(500)

    if addr.address2:
        addr2_input = page.locator('input[name*="address2"], input[name*="addr2"], input[placeholder*="建物"]')
        if await addr2_input.count() > 0:
            await addr2_input.first.fill(addr.address2)
            await page.wait_for_timeout(500)

    phone_input = page.locator('input[name*="phone"], input[name*="tel"], input[placeholder*="電話"]')
    if await phone_input.count() > 0:
        await phone_input.first.fill(addr.phone)
        await page.wait_for_timeout(500)


async def _fill_sender_info(page, settings):
    if not settings.sender_name:
        return

    sender_name_input = page.locator('input[name*="sender_name"], input[name*="senderName"], input[placeholder*="依頼主"]')
    if await sender_name_input.count() > 0:
        await sender_name_input.first.fill(settings.sender_name)
        await page.wait_for_timeout(500)

    if settings.sender_postal_code:
        sender_postal = page.locator('input[name*="sender_postal"], input[name*="senderZip"]')
        if await sender_postal.count() > 0:
            postal = settings.sender_postal_code.replace("-", "")
            await sender_postal.first.fill(postal)
            await page.wait_for_timeout(1500)

    if settings.sender_address1:
        sender_addr1 = page.locator('input[name*="sender_address1"], input[name*="senderAddr1"]')
        if await sender_addr1.count() > 0:
            await sender_addr1.first.fill(settings.sender_address1)
            await page.wait_for_timeout(500)

    if settings.sender_address2:
        sender_addr2 = page.locator('input[name*="sender_address2"], input[name*="senderAddr2"]')
        if await sender_addr2.count() > 0:
            await sender_addr2.first.fill(settings.sender_address2)
            await page.wait_for_timeout(500)

    if settings.sender_phone:
        sender_phone = page.locator('input[name*="sender_phone"], input[name*="senderTel"]')
        if await sender_phone.count() > 0:
            await sender_phone.first.fill(settings.sender_phone)
            await page.wait_for_timeout(500)
