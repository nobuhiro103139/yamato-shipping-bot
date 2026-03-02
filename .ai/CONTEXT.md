# yamato-shipping-bot Project Context

> This file is the single source of truth for AI agents working on this project.
> Read this first to understand the project's purpose, architecture, and current state.

## Project Overview

**Repository:** https://github.com/nobuhiro103139/yamato-shipping-bot
**Owner:** @nobuhiro103139 (TechRental)

**Purpose:** TechRental の運用DB（Supabase: techrental-core）に溜まっている `rentals` / `customers` を読み、ヤマト運輸「スマホで送る」(https://sp-send.kuronekoyamato.co.jp/) の Web フォームを Playwright で自動入力し、発送オペレーションを自動化する。

## Current Direction (重要)

- **データの正（source of truth）は Supabase DB**
  - Shopifyから直接読まない（webhookで既にDBに同期されている前提）
  - TechRental-ops の Supabase Edge Functions が Shopify webhook → DB 投入を担当
- Bot の役割は「発送対象の抽出 → ヤマト入力 → 結果（shipped）をDBへ反映」

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Browser Automation | Playwright (Python) - iPhone-like mobile emulation |
| Data Source | Supabase PostgREST (service_role key) |
| Notification | LINE Notify |
| Container | Docker / Docker Compose |
| Scheduler | GitHub Actions cron / (予定) Mac mini cron |

## Project Structure

```text
yamato-shipping-bot/
├── scripts/
│   ├── ship.py                 # CLI entry (ship/check/health)
│   ├── yamato_automation.py    # Yamato form automation via Playwright
│   ├── supabase_client.py      # Fetch rentals + update shipping_status via PostgREST
│   ├── notify.py               # LINE Notify
│   ├── models.py               # Pydantic models
│   └── config.py               # Settings (env)
├── .github/workflows/ship.yml  # Daily run (10:00 JST)
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── .ai/
```

## Import Dependency Graph

```text
scripts/models.py       (Pydantic models: RentalOrder, ShippingResult, etc.)
    ^
    |  imports PackageSize
    |
scripts/config.py       (Settings, get_settings)
    ^
    |  imports get_settings, config
    |
scripts/supabase_client.py   (PostgREST fetch/update)
scripts/yamato_automation.py  (Playwright automation)
scripts/notify.py             (LINE Notify)
    ^
    |  imports above
    |
scripts/ship.py              (CLI orchestrator)
```

**Forbidden path:** `scripts/models.py` must NEVER import `scripts/config.py` (circular import).

## Data Source (Supabase)

- Project: `techrental-core` (ID: `jinnapldrblkfzuypquj`)
- Primary tables:
  - `public.rentals` — shipping_status, shipping_date, delivery_time_slot, product_name, etc.
  - `public.customers` — name, postal_code, prefecture, city, address_line, phone, email
- The bot fetches rentals with:
  - `shipping_status IN ('pending','ready_to_ship')`
  - `rental_status IN ('pending','confirmed')`
  - `shipping_date <= today(JST)` for ship mode
- After success, it updates `rentals.shipping_status = 'shipped'`

## Architecture Decisions

1. **Why Playwright?** Yamato Transport doesn't offer a public API. Browser automation is the only option.
2. **Why Supabase?** TechRental-ops already syncs Shopify orders via webhook to Supabase. Reading from DB avoids redundant API calls and keeps a single source of truth.
3. **Mobile Emulation:** Yamato's smartphone interface is more automation-friendly than desktop.
4. **Sequential Processing:** Orders processed one-at-a-time to avoid overwhelming Yamato's servers.

## Key Data Models

All defined in `scripts/models.py`:

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `RentalOrder` | Rental order from Supabase | `order_id`, `order_number`, `shipping_address`, `items`, `package_size`, `delivery_date`, `delivery_time` |
| `ShippingResult` | Shipment outcome | `order_id`, `status`, `qr_code_path`, `error_message` |
| `ShippingAddress` | Recipient details | `last_name`, `first_name`, `postal_code`, `province`, `city`, `address1`, `phone` |
| `OrderItem` | Product line item | `title`, `quantity` |
| `PackageSize` | Enum: compact, S, M, L, LL | |
| `ShippingStatus` | Enum: PENDING, PROCESSING, COMPLETED, FAILED | Tracks shipment lifecycle |

## CLI Commands

| Command | Description |
|---------|-------------|
| `python -m scripts.ship` | Ship rentals ready today (default) |
| `python -m scripts.ship check` | List pending rentals (no automation) |
| `python -m scripts.ship health` | Show configuration status |

## Required Secrets / Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `SUPABASE_URL` | Supabase Project URL | Yes |
| `SUPABASE_SERVICE_ROLE_KEY` | PostgREST access (service_role) | Yes |
| `KURONEKO_LOGIN_ID` | Kuroneko Members login ID | Yes |
| `KURONEKO_PASSWORD` | Kuroneko Members password | Yes |
| `SENDER_NAME` | Sender name (address book entry name) | Yes |
| `SENDER_POSTAL_CODE` | Sender postal code | Yes |
| `SENDER_ADDRESS1` | Sender address line 1 | Yes |
| `SENDER_ADDRESS2` | Sender address line 2 | No |
| `SENDER_PHONE` | Sender phone number | Yes |
| `LINE_NOTIFY_TOKEN` | LINE Notify token | Yes |
| `DEFAULT_PACKAGE_SIZE` | Default package size (default: M) | No |
| `HEADLESS_BROWSER` | Playwright headless (default: true) | No |

## Operation Architecture

```text
Shopify webhook (TechRental-ops Edge Function)
  ↓
Supabase DB (techrental-core)
  ↓
GitHub Actions / Mac mini cron (10:00 JST daily)
  ↓
yamato-shipping-bot (Playwright + Xvfb)
  ↓
Supabase: rentals.shipping_status = shipped
  ↓
LINE Notify (QRコード画像)
```
