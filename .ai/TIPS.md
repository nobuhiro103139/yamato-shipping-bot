# Development Tips

> AI agents and developers: Append new tips to this file as you discover them.
> Each entry should include a date, tags, and description.
> This file is a living document - always add, never remove.

## How to Add a New Tip

Add entries under the appropriate category below. Use this format:

```markdown
### [YYYY-MM-DD] Brief title
**Tags:** `tag1`, `tag2`, `tag3`
Description of the tip, including any relevant code snippets or links.
```

If no category fits, create a new `## Category` section.

---

## Yamato Site Behavior

### [2026-02-09] Yamato URL and Access
**Tags:** `yamato`, `url`, `mobile-emulation`
- URL: `https://sp-send.kuronekoyamato.co.jp/` (smartphone version)
- PC access requires mobile emulation
- Use `playwright codegen --device="iPhone 13"` to record correct selectors

### [2026-02-09] Yamato Maintenance Hours
**Tags:** `yamato`, `maintenance`, `scheduling`
- Late night to early morning maintenance windows exist
- Form analysis and testing should be done outside these hours
- Automation runs should be scheduled for business hours (e.g., 10:00 AM)

### [2026-02-09] CSS Selectors Verified Against Live Site
**Tags:** `yamato`, `playwright`, `selector`, `verified`
**Last verified:** 2026-02-09 (via manual browser inspection with mobile emulation)
- Yamato uses Struts-based form bean naming: `viwb{pageId}ActionBean.{field}`
- Package settings page (Viwb2050): `viwb2050ActionBean.size`, `.itemName`, `.notProhibited`
- Recipient page (Viwb3040): `viwb3040ActionBean.lastName`, `.firstName`, `.zipCode`, `.address1`-`.address4`, `.phoneNumber`
- Sender page (Viwb3130): `viwb3130ActionBean.lastName`, `.firstName`, `.zipCode`, `.address3`, `.address4`, `.phoneNumber`
- Handling checkboxes: `input[name="handling"]` with `value="01"` (precision equipment), `"02"` (fragile), etc.
- Next button on package page: `a[data-action="Viwb2050Action_doNext.action"]`
- Address search button: `button#btnSearch`
- Yamato may update their HTML without notice - re-verify if automation breaks

### [2026-02-09] Yamato Form Flow (Guest Mode)
**Tags:** `yamato`, `flow`, `guest`
- Top page → "通常の荷物を送る" → "発払い" → "１個" → Package settings (Viwb2050)
- Package settings → "直接住所を入力する" → Recipient form (Viwb3040)
- Recipient form → Sender form (Viwb3130) → Confirmation → Payment
- Guest mode does NOT require Kuroneko Members login for form filling
- Payment step requires login or guest payment method

### [2026-02-09] Yamato Address Field Mapping
**Tags:** `yamato`, `address`, `form`
- `address1`: Prefecture (都道府県) - auto-filled by postal code lookup
- `address2`: City/district (市区町村) - auto-filled by postal code lookup (textarea)
- `address3`: Street/block number (丁目・番地)
- `address3opt`: Additional number (号)
- `address4`: Building name/room number (建物名・部屋番号)
- `companyName`: Company name (会社名) - optional
- After entering zip code, click `button#btnSearch` and wait 3000ms for AJAX lookup

## Playwright / Browser Automation

### [2026-02-09] Bot Detection Countermeasures
**Tags:** `playwright`, `bot-detection`, `stealth`
- `slow_mo=500ms` to mimic human interaction speed
- Real iPhone User-Agent string
- Touch events enabled via device emulation
- These are already configured in the codebase

### [2026-02-10] Xvfb + Headful Playwright = Anti-Bot Bypass
**Tags:** `playwright`, `bot-detection`, `xvfb`, `critical`, `verified`
**Verified:** 2026-02-10
- Xvfb (X Virtual Framebuffer) allows headful browsers on headless Linux VMs
- Command: `xvfb-run --auto-servernum --server-args="-screen 0 1280x960x24" python script.py`
- Yamato's anti-bot detection does NOT block Xvfb + headful Playwright
- This means GitHub Actions (ubuntu-latest) can run headful Playwright via Xvfb
- **auth.json session reuse does NOT work** - must login fresh every time
- `navigator.webdriver` returns normal headful values with Xvfb

### [2026-02-10] Login Redirect Chain Timing
**Tags:** `playwright`, `yamato`, `login`, `timing`, `critical`
- Login flow: sp-send → auth.kms.kuronekoyamato.co.jp → member.kms → sp-send
- Redirect takes 10-60 seconds, VERY inconsistent
- Use polling approach: check URL every 2 seconds for up to 60s
- Do NOT use `wait_for_url()` with fixed timeout - will fail intermittently
- If owner is using Yamato site simultaneously, login may fail (session conflict)
- Rate limiting: avoid rapid login attempts, wait 5+ minutes between retries

### [2026-02-09] Authentication Strategy
**Tags:** `playwright`, `auth`, `session`, `kuroneko`
- Kuroneko Members session is persisted via Playwright `storageState`
- Saved to `auth.json` after manual login
- **auth.json reuse DOES NOT WORK** (verified 2026-02-10) - landing page shown instead of logged-in state
- Must login fresh every automation run
- This simplifies the architecture (no artifact/session management needed)

### [2026-02-09] Postal Code Lookup Delay
**Tags:** `playwright`, `yamato`, `timing`, `ajax`
- After entering postal code, click `button#btnSearch` to trigger AJAX lookup
- Current wait: 3000ms (`TIMEOUT_POSTAL_LOOKUP_MS`)
- This auto-fills `address1` (prefecture) and `address2` (city)
- If address fields aren't populated, increase this timeout

## Shopify Integration

### [2026-02-09] GraphQL API Version
**Tags:** `shopify`, `api`, `version`
- Codebase uses version `2025-10` (defined as `SHOPIFY_API_VERSION` in `shopify_service.py`)
- Latest stable: `2026-01` (released Jan 2026)
- `2025-10` remains supported until Oct 2026
- Check https://shopify.dev/docs/api/usage/versioning for deprecation schedule

### [2026-02-09] Package Size Logic
**Tags:** `shopify`, `business-logic`, `package`
- Determined by total item quantity in the order
- 1 item -> S, 2-3 items -> M, 4-5 items -> L, 6+ items -> LL
- Defined via `PACKAGE_SIZE_THRESHOLDS` in `shopify_service.py`

## Code Architecture

### [2026-02-09] Circular Import Warning
**Tags:** `python`, `import`, `critical`
- `config.py` imports `PackageSize` from `models/order.py`
- **Never** import `config.py` from `models/order.py` - this will cause a circular import
- See dependency graph in `CONTEXT.md` for full import chain

### [2026-02-09] PII Masking in Logs
**Tags:** `security`, `logging`, `pii`
- CLI output masks personal information automatically
- Names: first character + `***`
- Addresses: prefecture + city only
- Always maintain this pattern when adding new log outputs

### [2026-02-09] CORS Configuration
**Tags:** `config`, `cors`, `frontend`
- Configurable via `CORS_ALLOWED_ORIGINS` environment variable
- Default: `localhost:5173,3000`
- Comma-separated list of allowed origins

### [2026-02-09] Product Name Truncation
**Tags:** `yamato`, `validation`, `form`
- Yamato form `itemName` field has a `maxlength="17"` attribute
- `PRODUCT_NAME_MAX_LENGTH = 17` in `yamato_automation.py`
- Concatenated item titles are truncated to fit

### [2026-02-09] Recipient Name Must Be Split Into Last/First
**Tags:** `yamato`, `form`, `shopify`, `model`
- Yamato requires separate `lastName` and `firstName` fields
- Shopify provides separate `firstName` and `lastName` via GraphQL
- `ShippingAddress` model has `last_name` and `first_name` fields
- `shopify_service.py` maps Shopify `lastName`/`firstName` directly

## Docker / Deployment

### [2026-02-09] Docker Architecture
**Tags:** `docker`, `infrastructure`
- Two services: `backend` (API server) and `runner` (CLI batch)
- Shared volumes: `yamato-data` (auth.json) and `yamato-qrcodes` (QR images)
- Non-root user in container for security
- Playwright Chromium is bundled in the Docker image

### [2026-02-09] Mac mini Deployment
**Tags:** `deployment`, `cron`, `production`
- Target production environment is a Mac mini (fallback if GitHub Actions fails)
- cron job at 10:00 AM daily: `docker compose run --rm runner ship`
- Logs to `/var/log/yamato-bot.log`

## Yamato Site HTML Structure (Verified 2026-02-10)

### [2026-02-10] setAction() Page Navigation Mechanism
**Tags:** `yamato`, `javascript`, `navigation`, `critical`
- Yamato mobile site uses `setAction()` JS function for ALL page transitions
- Pattern: `<a onclick="setAction('Viwb2015Action_doNextLeavePay.action')">`
- Implementation:
  ```javascript
  function setAction(actionStr){
      document.getElementById('form').setAttribute("action", actionStr);
      document.getElementById('form').submit();
  }
  ```
- Do NOT call `setAction()` via `page.evaluate()` - breaks session state
- Instead, click the `<a>` element which triggers the onclick handler naturally
- URLs follow pattern: `Viwb{pageId}Action_do{Action}.action`

### [2026-02-10] Image Buttons (Not Text)
**Tags:** `yamato`, `selector`, `button`, `critical`
- 発払い/着払い buttons are IMAGE buttons, not text
- Structure: `<a id="nextLeavePay" onclick="setAction(...)"><span class="img"><img alt="発払いで荷物を送る"></span></a>`
- `get_by_text("発払い")` will NOT find them
- Use: `page.locator("a#nextLeavePay").click()` or `page.get_by_alt_text("発払いで荷物を送る")`
- Key button IDs:
  - `a#nextLeavePay` - 発払いで荷物を送る
  - `a#nextArrivalPay` - 着払いで荷物を送る

### [2026-02-10] 「通常の荷物を送る」 Strict Mode Issue
**Tags:** `yamato`, `playwright`, `selector`, `strict-mode`
- `get_by_text("通常の荷物を送る")` matches 2 elements (span + li with caution text)
- Fix: use `.first` or `get_by_role("link", name="通常の荷物を送る")`

### [2026-02-10] Complete Verified Selectors for E2E Flow
**Tags:** `yamato`, `selector`, `verified`, `critical`
- Package settings (Viwb2050):
  - Size radio: `input[name="viwb2050ActionBean.size"]`
  - Item name: `input[name="viwb2050ActionBean.itemName"]`
  - Handling: `input[name="handling"]` (value="01" for precision)
  - Not prohibited: `input[name="viwb2050ActionBean.notProhibited"]`
  - Next: `a[data-action="Viwb2050Action_doNext.action"]`
- Recipient (Viwb3040):
  - Last name: `input[name="viwb3040ActionBean.lastName"]`
  - First name: `input[name="viwb3040ActionBean.firstName"]`
  - Zip: `input[name="viwb3040ActionBean.zipCode"]`
  - Address search: `button#btnSearch`
  - Address3: `input[name="viwb3040ActionBean.address3"]`
  - Address3opt: `input[name="viwb3040ActionBean.address3opt"]`
  - Phone: `input[name="viwb3040ActionBean.phoneNumber"]`
  - Next: `a#next`
- Delivery (Viwb4100):
  - Shipping date: `select[name="viwb4100ActionBean.dateToShip"]`
  - Delivery date: `select[name="viwb4100ActionBean.dateToReceive"]`
  - Delivery time: `select[name="viwb4100ActionBean.timeToReceive"]`
