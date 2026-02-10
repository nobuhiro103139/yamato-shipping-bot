"""E2E test: Xvfb + headful Playwright end-to-end Yamato automation test.

Run with:
    xvfb-run --auto-servernum --server-args="-screen 0 1280x960x24" python scripts/test_e2e_xvfb.py

Requires env vars: YAMATO_USER, YAMATO_PASS

Key design decisions:
- Login: Poll for redirect (up to 60s) instead of wait_for_url with fixed timeout
- Buttons: Click by element ID (a#nextLeavePay) - buttons are images, not text
- Navigation: Yamato uses setAction() JS for page transitions - click the <a> naturally
- Error detection: Check for session-expired page after each navigation
"""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

YAMATO_SEND_URL = "https://sp-send.kuronekoyamato.co.jp/"
IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6 Mobile/15E148 Safari/604.1"
)
SCREENSHOT_DIR = Path("/tmp/e2e_test")
SCREENSHOT_DIR.mkdir(exist_ok=True)

KURONEKO_ID = os.environ["YAMATO_USER"]
KURONEKO_PW = os.environ["YAMATO_PASS"]

DEVICE = dict(
    user_agent=IPHONE_UA,
    viewport={"width": 390, "height": 844},
    device_scale_factor=3,
    is_mobile=True,
    has_touch=True,
)

STEP = [0]
RESULTS = {}

async def ss(page, name):
    STEP[0] += 1
    path = str(SCREENSHOT_DIR / f"{STEP[0]:02d}_{name}.png")
    await page.screenshot(path=path, full_page=True)
    print(f"  [{STEP[0]:02d}] {name}")
    return path

async def check_error(page):
    """Check if the error page is shown."""
    content = await page.content()
    if "本サービスを継続する" in content:
        print("  ERROR: Session expired / invalid state!")
        return True
    return False

async def dump_page(page, label=""):
    """Dump page info for debugging."""
    info = await page.evaluate("""() => {
        const form = document.getElementById('form');
        const action = form ? form.action : 'no form';
        const links = Array.from(document.querySelectorAll('a'))
            .filter(a => a.offsetParent !== null && a.id)
            .map(a => ({ id: a.id, text: a.textContent.trim().substring(0,30), onclick: (a.getAttribute('onclick')||'').substring(0,60) }));
        const inputs = Array.from(document.querySelectorAll('input:not([type=hidden]),select,textarea'))
            .filter(e => e.offsetParent !== null)
            .map(e => ({ tag: e.tagName, type: e.type || '', name: e.name, id: e.id }));
        const imgs = Array.from(document.querySelectorAll('img[alt]'))
            .filter(e => e.offsetParent !== null)
            .map(e => ({ alt: e.alt, parentTag: e.parentElement?.tagName, parentId: e.parentElement?.closest('a')?.id || '' }));
        return { action, links: links.slice(0,15), inputs: inputs.slice(0,15), imgs: imgs.slice(0,10) };
    }""")
    if label:
        print(f"  --- {label} ---")
    print(f"  Form action: {info['action']}")
    if info['links']:
        print(f"  Links with ID: {info['links']}")
    if info['inputs']:
        print(f"  Inputs: {info['inputs']}")
    if info['imgs']:
        print(f"  Images: {info['imgs']}")
    return info

async def run():
    print("=" * 60)
    print("E2E TEST v6: ID-based clicks + better login")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(**DEVICE)
        page = await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => false });")

        async def handle_dialog(dialog):
            print(f"  DIALOG [{dialog.type}]: {dialog.message}")
            await dialog.accept()
        page.on("dialog", handle_dialog)

        try:
            # ===== STEP 1: Navigate =====
            print("\n=== Step 1: Navigate ===")
            await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            await ss(page, "initial")
            RESULTS["1_navigate"] = "OK"

            # ===== STEP 2: Login =====
            print("\n=== Step 2: Login ===")

            # Check if sp-send landing page needs login
            content = await page.content()
            needs_login = "ログインして利用する" in content

            if needs_login:
                # Click "クロネコメンバーズにログインして利用する" to start auth flow
                login_btn = page.get_by_text("ログインして利用する", exact=False)
                if await login_btn.count() > 0:
                    await login_btn.first.click()
                    await page.wait_for_timeout(5000)
                    print(f"  Clicked login button. URL: {page.url}")

            if "auth.kms" in page.url:
                await page.locator('#login-form-id').fill(KURONEKO_ID)
                await page.locator('#login-form-password').fill(KURONEKO_PW)
                await ss(page, "login_filled")
                await page.locator('#login-form-submit').click()

                # Poll for redirect - wait up to 60s
                print("  Waiting for login redirect...")
                for i in range(30):
                    await page.wait_for_timeout(2000)
                    url = page.url
                    if "sp-send" in url:
                        print(f"  Redirected to sp-send after {(i+1)*2}s")
                        break
                    elif "member" in url:
                        print(f"  On member page after {(i+1)*2}s, navigating to sp-send...")
                        await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded")
                        await page.wait_for_timeout(5000)
                        break
                    elif i % 5 == 4:
                        print(f"  Still on: {url[:60]}... ({(i+1)*2}s)")
                else:
                    print(f"  Login redirect timeout after 60s. URL: {page.url}")
                    await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded")
                    await page.wait_for_timeout(5000)

            await page.wait_for_timeout(2000)

            # If still on landing page, try SSO via "ログインして利用する" again
            content = await page.content()
            logout_check = page.locator('text=ログアウト')
            is_actually_logged_in = (await logout_check.count() > 0 and await logout_check.first.is_visible())
            if "ログインして利用する" in content and not is_actually_logged_in:
                print("  Session not established on sp-send, retrying SSO...")
                sso_btn = page.get_by_text("ログインして利用する", exact=False)
                if await sso_btn.count() > 0:
                    await sso_btn.first.click()
                    await page.wait_for_timeout(8000)
                    print(f"  After SSO retry, URL: {page.url}")
                    # If auth page appears again (already logged in), it might auto-redirect
                    if "auth.kms" in page.url:
                        print("  Auth page shown again, waiting for auto-redirect...")
                        for i in range(15):
                            await page.wait_for_timeout(2000)
                            if "sp-send" in page.url:
                                print(f"  Auto-redirected after {(i+1)*2}s")
                                break
                        else:
                            await page.goto(YAMATO_SEND_URL, wait_until="domcontentloaded")
                            await page.wait_for_timeout(5000)

            await page.wait_for_timeout(2000)
            # Robust login detection: check visible state of page
            logout_btn = page.locator('text=ログアウト').first
            logout_visible = await logout_btn.is_visible() if await page.locator('text=ログアウト').count() > 0 else False
            content = await page.content()
            has_login_btn = "ログインして利用する" in content
            logged_in = logout_visible and not has_login_btn
            print(f"  Login: {'OK' if logged_in else 'FAILED'} (logout_visible={logout_visible}, has_login_btn={has_login_btn})")
            print(f"  Current URL: {page.url}")
            await ss(page, "after_login")

            if not logged_in:
                RESULTS["2_login"] = "FAILED"
                raise RuntimeError("Login failed - page still shows login button")
            RESULTS["2_login"] = "OK"

            # ===== STEP 3: 通常の荷物を送る =====
            print("\n=== Step 3: 通常の荷物を送る ===")
            normal = page.get_by_role("link", name="通常の荷物を送る 通常の荷物を送る")
            if await normal.count() > 0:
                await normal.first.click()
                await page.wait_for_timeout(3000)
                print(f"  Clicked. URL: {page.url}")
                RESULTS["3_normal"] = "OK"
            else:
                # Fallback: click by text
                await page.get_by_text("通常の荷物を送る").first.click()
                await page.wait_for_timeout(3000)
                RESULTS["3_normal"] = "OK (fallback)"
            await ss(page, "normal_selected")

            if await check_error(page):
                RESULTS["3_normal"] = "ERROR"
                raise RuntimeError("Error after 通常の荷物を送る")

            # ===== STEP 4: 発払い =====
            print("\n=== Step 4: 発払い ===")
            await dump_page(page, "Before 発払い")

            # Click a#nextLeavePay directly
            prepay = page.locator("a#nextLeavePay")
            if await prepay.count() > 0:
                await prepay.click()
                await page.wait_for_timeout(3000)
                print(f"  Clicked a#nextLeavePay. URL: {page.url}")
            else:
                print("  a#nextLeavePay not found, trying alt text...")
                img = page.get_by_alt_text("発払いで荷物を送る")
                if await img.count() > 0:
                    await img.first.click()
                    await page.wait_for_timeout(3000)
                    print("  Clicked img alt=発払い")
                else:
                    print("  No prepay button found!")
                    RESULTS["4_prepay"] = "NOT FOUND"
                    await ss(page, "no_prepay")
                    raise RuntimeError("発払い button not found")

            await ss(page, "after_prepay")
            if await check_error(page):
                RESULTS["4_prepay"] = "ERROR (session)"
                raise RuntimeError("Error after 発払い")

            content = await page.content()
            print(f"  Has 個: {'個' in content}, Has サイズ: {'サイズ' in content}")
            await dump_page(page, "After 発払い")
            RESULTS["4_prepay"] = "OK"

            # ===== STEP 5: Package count =====
            print("\n=== Step 5: Package count ===")
            one_btn = page.locator("a#one")
            if await one_btn.count() > 0:
                await one_btn.click()
                await page.wait_for_timeout(3000)
                print("  Clicked a#one (１個)")
                RESULTS["5_count"] = "OK"
            else:
                info = await dump_page(page, "Count page")
                RESULTS["5_count"] = "NOT FOUND"

            await ss(page, "after_count")
            if await check_error(page):
                RESULTS["5_count"] = "ERROR"
                raise RuntimeError("Error after count")

            # ===== STEP 6: Package settings =====
            print("\n=== Step 6: Package settings ===")
            await dump_page(page, "Package settings page")

            # Size: select S via JS (radios are hidden, styled as label boxes)
            size_set = await page.evaluate("""
                () => {
                    const radios = document.querySelectorAll('input[name="viwb2050ActionBean.size"]');
                    const info = [];
                    for (const r of radios) {
                        const lbl = r.closest('label') || r.parentElement;
                        info.push({value: r.value, text: lbl?.textContent?.trim()?.substring(0,30) || ''});
                    }
                    // Click S label
                    for (const r of radios) {
                        if (r.value === 'S') {
                            r.checked = true;
                            r.dispatchEvent(new Event('change', {bubbles: true}));
                            const lbl = r.closest('label');
                            if (lbl) lbl.click();
                            return {selected: 'S', all: info};
                        }
                    }
                    return {selected: null, all: info};
                }
            """)
            print(f"  Size radios: {size_set}")

            # Product name
            item = page.locator('input[name="viwb2050ActionBean.itemName"]')
            if await item.count() > 0:
                await item.first.fill("スマートフォン")
                print("  Product: スマートフォン")
            else:
                print("  WARNING: itemName not found")

            # Handling: click 精密機械 image/label via JS
            await page.evaluate("""
                () => {
                    const imgs = document.querySelectorAll('img[alt="精密機械"]');
                    if (imgs.length > 0) {
                        const parent = imgs[0].closest('label') || imgs[0].closest('a') || imgs[0].parentElement;
                        if (parent) parent.click();
                    }
                }
            """)
            await page.wait_for_timeout(500)
            print("  Handling: 精密機械 (via JS)")

            # Not prohibited checkbox via JS
            await page.evaluate("""
                () => {
                    const cb = document.querySelector('input[name="viwb2050ActionBean.notProhibited"]');
                    if (cb && !cb.checked) {
                        cb.checked = true;
                        cb.dispatchEvent(new Event('change', {bubbles: true}));
                        const lbl = cb.closest('label');
                        if (lbl) lbl.click();
                    }
                }
            """)
            await page.wait_for_timeout(500)
            print("  Prohibited: confirmed (via JS)")

            await ss(page, "package_filled")

            # Next button - look for submit link/button with setAction
            next_clicked = False
            for sel in [
                'a[data-action="Viwb2050Action_doNext.action"]',
                'a#next',
                'a[onclick*="Viwb2050Action_doNext"]',
            ]:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    await loc.first.click(force=True)
                    await page.wait_for_timeout(3000)
                    print(f"  Next clicked: {sel}")
                    next_clicked = True
                    break
            if not next_clicked:
                # Try clicking by visible text
                for txt in ["荷物内容を入力してください", "次へ", "次へ進む"]:
                    btn = page.get_by_text(txt, exact=False)
                    if await btn.count() > 0:
                        await btn.first.click()
                        await page.wait_for_timeout(3000)
                        print(f"  Next clicked: '{txt}'")
                        next_clicked = True
                        break
            if not next_clicked:
                # Last resort: find any submit-like link via JS
                await page.evaluate("""
                    () => {
                        const links = document.querySelectorAll('a[onclick*="doNext"], a[onclick*="setAction"]');
                        for (const a of links) {
                            if (a.offsetParent !== null) { a.click(); return true; }
                        }
                        const form = document.getElementById('form');
                        if (form) { form.submit(); return true; }
                        return false;
                    }
                """)
                await page.wait_for_timeout(3000)
                print("  Next: JS fallback")

            await ss(page, "after_pkg_next")
            RESULTS["6_package"] = "FILLED" if await item.count() > 0 else "PARTIAL"

            if await check_error(page):
                RESULTS["6_package"] = "ERROR"
                raise RuntimeError("Error after package settings")

            # ===== STEP 7: Address method =====
            print("\n=== Step 7: Address method ===")
            await dump_page(page, "Address method")
            direct = page.get_by_text("直接住所を入力する", exact=False)
            if await direct.count() > 0:
                await direct.first.click()
                await page.wait_for_timeout(3000)
                print("  Selected direct input")
                RESULTS["7_addr_method"] = "OK"
            else:
                print("  Direct input not found (may auto-skip)")
                RESULTS["7_addr_method"] = "SKIPPED"
            await ss(page, "address_method")

            # ===== STEP 8: Recipient =====
            print("\n=== Step 8: Recipient ===")
            await dump_page(page, "Recipient form")

            filled_count = 0
            for sel, val, desc in [
                ('input[name="viwb3040ActionBean.lastName"]', "大倉", "姓"),
                ('input[name="viwb3040ActionBean.firstName"]', "愛子", "名"),
            ]:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    await loc.first.fill(val)
                    print(f"  {desc}: {val}")
                    filled_count += 1
                else:
                    print(f"  NOT FOUND: {desc}")

            # Postal code
            zip_loc = page.locator('input[name="viwb3040ActionBean.zipCode"]')
            if await zip_loc.count() > 0:
                await zip_loc.first.fill("2060024")
                print("  Zip: 2060024")
                filled_count += 1
                search = page.locator("button#btnSearch")
                if await search.count() > 0:
                    await search.first.click()
                    await page.wait_for_timeout(3000)
                    print("  Postal searched")
            await ss(page, "after_postal")

            # Area selection - look for 諏訪
            content = await page.content()
            if "諏訪" in content:
                suwa = page.get_by_text("諏訪", exact=False)
                for i in range(await suwa.count()):
                    text = await suwa.nth(i).text_content()
                    if text and "諏訪" in text and len(text.strip()) < 15:
                        await suwa.nth(i).click()
                        await page.wait_for_timeout(2000)
                        print(f"  Area: {text.strip()}")
                        break

            # 丁目
            content = await page.content()
            if "1丁目" in content:
                chome = page.get_by_text("1丁目", exact=True)
                if await chome.count() > 0:
                    await chome.first.click()
                    await page.wait_for_timeout(2000)
                    print("  丁目: 1丁目")
            await ss(page, "after_area")

            # Address detail
            for sel, val, desc in [
                ('input[name="viwb3040ActionBean.address3"]', "27", "番地"),
                ('input[name="viwb3040ActionBean.address3opt"]', "3", "号"),
            ]:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    await loc.first.fill(val)
                    print(f"  {desc}: {val}")
                    filled_count += 1

            # Phone
            phone = page.locator('input[name="viwb3040ActionBean.phoneNumber"]')
            if await phone.count() > 0:
                await phone.first.fill("09029421016")
                print("  Phone: 09029421016")
                filled_count += 1

            # Notification email
            notify_cb = page.locator('input[name*="notifyFlg"]')
            if await notify_cb.count() > 0:
                if not await notify_cb.first.is_checked():
                    await notify_cb.first.check(force=True)
                    await page.wait_for_timeout(500)
                email = page.locator('input[name*="mailAddress"]')
                if await email.count() > 0:
                    await email.first.fill("aico-32@docomo.ne.jp")
                    print("  Email: aico-32@docomo.ne.jp")
                    filled_count += 1

            # Uncheck address book
            addr_cb = page.locator('input[name*="addAddressBook"]')
            if await addr_cb.count() > 0 and await addr_cb.first.is_checked():
                await addr_cb.first.uncheck(force=True)
                print("  Address book unchecked")

            await ss(page, "recipient_filled")
            RESULTS["8_recipient"] = f"FILLED ({filled_count} fields)"

            # Next
            next_btn = page.locator("a#next")
            if await next_btn.count() > 0:
                await next_btn.first.click(force=True)
                await page.wait_for_timeout(3000)
                print("  Next clicked")
            await ss(page, "after_recipient")

            if await check_error(page):
                RESULTS["8_recipient"] = "ERROR"
                raise RuntimeError("Error after recipient")

            # ===== STEP 9: Sender =====
            print("\n=== Step 9: Sender ===")
            await dump_page(page, "Sender page")
            addr_book = page.get_by_text("アドレス帳から選択", exact=False)
            if await addr_book.count() > 0:
                await addr_book.first.click()
                await page.wait_for_timeout(2000)
                print("  Opened address book")

                for sender in ["フツテック", "TechRental", "加藤"]:
                    loc = page.get_by_text(sender, exact=False)
                    if await loc.count() > 0:
                        await loc.first.click()
                        await page.wait_for_timeout(2000)
                        print(f"  Sender: {sender}")
                        RESULTS["9_sender"] = f"OK ({sender})"
                        break
                else:
                    RESULTS["9_sender"] = "NO MATCH"
            else:
                RESULTS["9_sender"] = "NO ADDRESS BOOK"

            await ss(page, "sender_done")
            next_btn = page.locator("a#next")
            if await next_btn.count() > 0:
                await next_btn.first.click(force=True)
                await page.wait_for_timeout(3000)
            await ss(page, "after_sender")

            # ===== STEP 10: Location =====
            print("\n=== Step 10: Shipping location ===")
            content = await page.content()
            await dump_page(page, "Location page")
            for loc_text in ["近くから発送", "コンビニから発送"]:
                loc = page.get_by_text(loc_text, exact=False)
                if await loc.count() > 0:
                    await loc.first.click()
                    await page.wait_for_timeout(2000)
                    print(f"  Location: {loc_text}")
                    RESULTS["10_location"] = "OK"
                    break
            else:
                RESULTS["10_location"] = "NOT FOUND"
            await ss(page, "location")

            # ===== STEP 11: Date/time =====
            print("\n=== Step 11: Date/time ===")
            ship_sel = page.locator('select[name="viwb4100ActionBean.dateToShip"]')
            if await ship_sel.count() > 0:
                opts = await ship_sel.locator("option").evaluate_all("els => els.map(e => ({v: e.value, t: e.textContent.trim()}))")
                print(f"  Ship options: {opts[:5]}")
                for o in opts:
                    if o['v']:
                        await ship_sel.select_option(value=o['v'])
                        await page.wait_for_timeout(2000)
                        print(f"  Ship date: {o['t']}")
                        break

            delivery_sel = page.locator('select[name="viwb4100ActionBean.dateToReceive"]')
            if await delivery_sel.count() > 0:
                opts = await delivery_sel.locator("option").evaluate_all("els => els.map(e => ({v: e.value, t: e.textContent.trim()}))")
                print(f"  Delivery options: {opts[:5]}")
                for o in opts:
                    if "12" in o.get('t', '') or o.get('v') == "20260212":
                        await delivery_sel.select_option(value=o['v'])
                        await page.wait_for_timeout(2000)
                        print(f"  Delivery: {o['t']}")
                        RESULTS["11_datetime"] = "OK"
                        break

            time_sel = page.locator('select[name="viwb4100ActionBean.timeToReceive"]')
            if await time_sel.count() > 0:
                opts = await time_sel.locator("option").evaluate_all("els => els.map(e => ({v: e.value, t: e.textContent.trim()}))")
                print(f"  Time options: {opts[:8]}")
                for o in opts:
                    if "0812" in o.get('v', '') or "8" in o.get('t', ''):
                        await time_sel.select_option(value=o['v'])
                        await page.wait_for_timeout(1500)
                        print(f"  Time: {o['t']}")
                        break

            await ss(page, "datetime_filled")

            next_btn = page.locator("a#next")
            if await next_btn.count() > 0:
                await next_btn.first.click(force=True)
                await page.wait_for_timeout(3000)
            await ss(page, "after_datetime")

            # ===== STEP 12: Final state =====
            print("\n=== Step 12: FINAL STATE (NOT confirming) ===")
            content = await page.content()
            for kw in ["確認", "下書き", "お支払い", "送り状を登録", "QR", "大倉", "愛子", "スマートフォン", "諏訪"]:
                found = kw in content
                print(f"  {kw}: {found}")
            await dump_page(page, "Final page")
            await ss(page, "final")

        except Exception as e:
            print(f"\nERROR: {e}")
            await ss(page, "error")
            import traceback
            traceback.print_exc()
        finally:
            await browser.close()

    # Print summary
    print(f"\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    for k, v in RESULTS.items():
        status = "OK" if "OK" in v or "FILLED" in v else "NG"
        print(f"  {k}: {v} [{status}]")
    print(f"Screenshots: {STEP[0]} files in {SCREENSHOT_DIR}")
    print(f"{'='*60}")

asyncio.run(run())
