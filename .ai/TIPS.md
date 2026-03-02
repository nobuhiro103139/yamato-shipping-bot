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

## Supabase Integration

### [2026-03-02] Supabase PostgREST で直接 rentals を取得する方式に変更
**Tags:** `supabase`, `architecture`, `data-source`
- Shopify API 経由を廃止し、Supabase PostgREST で `rentals` + `customers` を直接取得
- Project: `techrental-core` (ID: `jinnapldrblkfzuypquj`)
- 取得条件: `shipping_status IN ('pending','ready_to_ship')` AND `rental_status IN ('pending','confirmed')`
- ship コマンド: さらに `shipping_date <= today(JST)` で当日分に絞る
- 成功後に `PATCH rentals` で `shipping_status = 'shipped'` に更新
- `customers` テーブルの `name` は姓名一体（例: '田中 太郎'）→ スペース区切りで split

### [2026-03-02] delivery_time_slot のマッピング
**Tags:** `supabase`, `yamato`, `business-logic`
- DB上は人間可読な文字列（例: `8:00~12:00`, `14:00~16:00`）
- ヤマトフォームの radio value（`1`, `3`, `4` 等）に変換が必要
- カンマ区切りで複数指定されている場合は最初のスロットを採用
- `指定なし` は `DeliveryTimeSlot.NONE` にマッピング

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
- Target production environment is a Mac mini
- cron job at 10:00 AM daily: `docker compose run --rm runner ship`
- Logs to `/var/log/yamato-bot.log`
