# yamato-shipping-bot Project Context

> This file is the single source of truth for AI agents working on this project.
> Read this first to understand the project's purpose, architecture, and current state.

## Project Overview

**Repository:** https://github.com/nobuhiro103139/yamato-shipping-bot
**Owner:** @nobuhiro103139 (TechRental)
**Purpose:** TechRental の Shopify 注文データから配送先住所を自動取得し、ヤマト運輸「宅急便をスマホで送る」(https://sp-send.kuronekoyamato.co.jp/) の Web フォームに Playwright で自動入力 → オンライン決済 → QR コード取得までを自動化するシステム。

## Business Background

- TechRental はレンタル機器の配送でヤマト運輸を使っている
- B2 クラウドは契約/コスト面で利用不可
- 「スマホで送る」の Web 版を Playwright でモバイルエミュレーション操作する方式を採用
- 手作業をゼロにしたい。オーナーは環境構築が苦手なので、Docker 一発で動く形を要求

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Browser Automation | Playwright (Python) - iPhone mobile emulation |
| Data Source | Shopify Admin API (GraphQL, version 2025-10) |
| Backend | FastAPI (Python 3.12, Poetry) |
| Frontend | React (Vite + TypeScript + Tailwind CSS) |
| Session Management | Playwright storageState (auth.json) |
| Container | Docker / Docker Compose |

## Project Structure

```
backend/app/
├── main.py              # FastAPI entry point (CORS configurable)
├── cli.py               # CLI runner (ship/check/health)
├── config.py            # pydantic-settings (env vars, validation)
├── models/order.py      # Pydantic models (ShopifyOrder, ShippingResult, etc.)
├── routers/             # orders.py, shipping.py
└── services/
    ├── shopify_service.py      # Shopify GraphQL API integration
    └── yamato_automation.py    # Playwright automation engine (core)
frontend/src/            # React dashboard (incomplete)
Dockerfile               # Python 3.12-slim + Playwright + non-root user
docker-compose.yml       # backend (API) + runner (CLI) services
```

## Architecture Decisions

1. **Why Playwright?** Yamato Transport doesn't offer a public API. Browser automation is the only option.
2. **Why Both Web and CLI?** Web UI for ad-hoc/interactive use; CLI for reliable scheduled batch processing.
3. **Session Persistence:** Manual login once -> save Playwright `storageState` -> reuse for all automated runs.
4. **Mobile Emulation:** Yamato's smartphone interface (`sp-send.kuronekoyamato.co.jp`) is more automation-friendly than desktop.
5. **Sequential Processing:** Orders processed one-at-a-time to avoid overwhelming Yamato's servers.

## Key Data Models

- `ShopifyOrder` - Unfulfilled Shopify order with shipping address and items
- `ShippingResult` - Outcome of a shipment (status: PENDING/PROCESSING/COMPLETED/FAILED)
- `ShippingAddress` - Recipient details (name, postal code, address, phone)
- `PackageSize` - Enum: S, M, L, LL (determined by item quantity)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Health check |
| GET | `/api/orders/unfulfilled` | Fetch unfulfilled orders from Shopify |
| POST | `/api/shipping/process` | Process single order shipment |
| POST | `/api/shipping/init-auth` | Initialize Kuroneko Members manual login |

## CLI Commands

| Command | Description |
|---------|-------------|
| `python -m app.cli ship` | Process all unfulfilled orders |
| `python -m app.cli check` | List unfulfilled orders (dry run) |
| `python -m app.cli health` | Display configuration status |

## Required Secrets / Environment Variables

| Variable | Description |
|----------|-------------|
| `SHOPIFY_STORE_URL` | Shopify store URL |
| `SHOPIFY_ACCESS_TOKEN` | Shopify Admin API token |
| `KURONEKO_LOGIN_ID` | Kuroneko Members login ID |
| `KURONEKO_PASSWORD` | Kuroneko Members password |
| `SENDER_NAME` | Sender name |
| `SENDER_POSTAL_CODE` | Sender postal code |
| `SENDER_ADDRESS1` | Sender address line 1 |
| `SENDER_ADDRESS2` | Sender address line 2 (optional) |
| `SENDER_PHONE` | Sender phone number |
| `HEADLESS_BROWSER` | Headless mode (true/false) |
| `AUTH_STATE_PATH` | Auth state file path (default: auth.json) |

## Operation Architecture

```
Development: AI agents (Devin/Claude Code) for dev & review
  |
Deploy: Docker image on Mac mini
  |
Execution: cron scheduled or manual `docker compose run`
  |
Monitoring: Log review, error notification
```

## Important Warnings

- **Circular import:** `config.py` imports `PackageSize` from `models/order.py`. Do NOT import `config.py` from `models/order.py`.
- **CSS Selectors:** All selectors in `yamato_automation.py` are best-guess estimates. They need real-site verification.
- **PII Masking:** CLI log output masks personal info (first char of name + ***, address shows only prefecture + city).
- **Yamato Maintenance:** Late night to early morning maintenance windows exist. Don't run form analysis during those hours.
