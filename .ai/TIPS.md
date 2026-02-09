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

### [2026-02-09] Authentication Strategy
**Tags:** `playwright`, `auth`, `session`, `kuroneko`
- Kuroneko Members session is persisted via Playwright `storageState`
- Saved to `auth.json` after manual login
- Session expires periodically - re-login required when expired
- Use `POST /api/shipping/init-auth` to trigger manual login flow

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
- Shared volumes: `yamato-data` (auth.json) and `yamato-results` (processing results)
- Non-root user in container for security
- Browser Use + Playwright Chromium are bundled in the Docker image

### [2026-02-09] Mac mini Deployment
**Tags:** `deployment`, `cron`, `production`
- Target production environment is a Mac mini
- cron job at 9:00 AM daily: `docker compose run --rm runner ship`
- Logs to `/var/log/yamato-bot.log`
- **HEADLESS_BROWSER=false** is required for Mac mini (Browser Use needs headful mode)

## Browser Use / LLM

### [2026-02-09] Browser Use Architecture Decision
**Tags:** `browser-use`, `architecture`, `critical`
- Browser Use chosen over Playwright direct and OpenClaw
- Reason: Yamato blocks headless Playwright (anti-bot detection)
- Reason: OpenClaw is overkill for "1 day / 1 batch" use case
- Browser Use uses LLM to drive browser via natural language task prompts
- More resilient to HTML structure changes (no CSS selector dependency)
- Trade-off: slower (LLM inference) and costs API fees per shipment

### [2026-02-09] Browser Use Task Prompt Design
**Tags:** `browser-use`, `prompt`, `yamato`
- Task prompt is written in Japanese (matches Yamato's UI language)
- Prompt includes step-by-step numbered instructions
- Each form field is explicitly named with expected value
- Includes fallback instructions (e.g., "if login page appears, login with...")
- Prompt template is in `yamato_agent.py::_build_task_prompt()`

### [2026-02-09] Browser Use Mobile Emulation
**Tags:** `browser-use`, `mobile`, `emulation`
- iPhone emulation: UA string, 390x844 viewport, 3x device scale factor
- `wait_between_actions=1.0` to mimic human interaction speed
- `allowed_domains` restricts navigation to `*.kuronekoyamato.co.jp`
- `storage_state` loads auth.json if it exists for session persistence

### [2026-02-09] LLM Provider Configuration
**Tags:** `llm`, `config`, `browser-use`
- Default: OpenAI GPT-4o (best balance of speed and accuracy for form filling)
- Alternative: Anthropic Claude (set `LLM_PROVIDER=anthropic`)
- API key is required: `LLM_API_KEY` in .env
- langchain abstractions used for provider flexibility
- browser-use and langchain-openai are required deps; langchain-anthropic is optional

### [2026-02-09] Playwright Anti-Bot Detection (Historical)
**Tags:** `playwright`, `anti-bot`, `yamato`, `historical`
- Headless Playwright: Yamato redirects to login page (session invalidated)
- Headful Playwright in Devin: Display conflict (system constraint)
- CDP connection (connect_over_cdp): shared_worker assertion error
- Chrome Cookie DB extraction: encrypted_value column, value column empty
- **Conclusion:** Direct Playwright automation in cloud/CI environments is not viable for Yamato
- Browser Use with headful mode on Mac mini is the solution

### [2026-02-09] Shipment Data Format (shipments.json)
**Tags:** `data`, `shipment`, `json`
- Array of Shipment objects
- Required fields: `recipient_last_name`, `recipient_postal_code`, `recipient_phone`
- Optional: `recipient_first_name`, `recipient_email`, `recipient_building`, etc.
- `package_size`: "compact" (default), "S", "M", "L", "LL"
- `delivery_time`: free-text (e.g., "18:00~20:00") - agent interprets from dropdown
- See `backend/shipments.example.json` for sample format
