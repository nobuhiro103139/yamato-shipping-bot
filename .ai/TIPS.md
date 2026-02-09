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

### [2026-02-09] CSS Selectors are Estimates
**Tags:** `yamato`, `playwright`, `selector`, `risk`
- All selectors in `yamato_automation.py` (e.g., `input[name*="postal"]`) are best-guess
- Must verify with `playwright codegen --device="iPhone 13"` on the real site
- Yamato may update their HTML without notice - selectors may break

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
- After entering postal code, Yamato's form triggers an AJAX lookup
- Current wait: 1500ms (`TIMEOUT_POSTAL_LOOKUP_MS`)
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
- Yamato form has a 30-character limit for product names
- `PRODUCT_NAME_MAX_LENGTH = 30` in `yamato_automation.py`
- Concatenated item titles are truncated to fit

## Docker / Deployment

### [2026-02-09] Docker Architecture
**Tags:** `docker`, `infrastructure`
- Two services: `backend` (API server) and `runner` (CLI batch)
- Shared volumes: `yamato-data` (auth.json) and `yamato-qrcodes` (QR images)
- Non-root user in container for security
- Playwright Chromium is bundled in the Docker image

### [2026-02-09] Mac mini Deployment
**Tags:** `deployment`, `cron`, `production`
- Target production environment is a Mac mini
- cron job at 10:00 AM daily: `docker compose run --rm runner ship`
- Logs to `/var/log/yamato-bot.log`
