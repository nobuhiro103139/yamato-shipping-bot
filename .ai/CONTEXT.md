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

```text
yamato-shipping-bot/
├── .ai/                         # AI agent context (you are here)
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point (CORS configurable)
│   │   ├── cli.py               # CLI runner (ship/check/health)
│   │   ├── config.py            # pydantic-settings (env vars, validation)
│   │   ├── __main__.py          # CLI entry point
│   │   ├── models/
│   │   │   └── order.py         # Pydantic models (ShopifyOrder, ShippingResult, etc.)
│   │   ├── routers/
│   │   │   ├── orders.py        # GET /api/orders/unfulfilled
│   │   │   └── shipping.py      # POST /api/shipping/process, init-auth
│   │   └── services/
│   │       ├── shopify_service.py    # Shopify GraphQL API integration
│   │       └── yamato_automation.py  # Playwright automation engine (core)
│   ├── .env.example
│   └── pyproject.toml
├── frontend/
│   └── src/
│       ├── App.tsx              # Main application component
│       ├── api.ts               # Backend API client
│       ├── types.ts             # TypeScript type definitions
│       └── components/          # UI components
├── Dockerfile                   # Python 3.12-slim + Playwright + non-root user
├── docker-compose.yml           # backend (API) + runner (CLI) services
└── README.md
```

## Import Dependency Graph

Understanding the import chain is critical to avoid circular imports.

```text
models/order.py          (defines: PackageSize, ShippingStatus, ShopifyOrder, ShippingResult, etc.)
    ^
    |  imports PackageSize
    |
config.py                (defines: Settings, get_settings)
    ^
    |  imports get_settings
    |
services/shopify_service.py    (imports: config, models)
services/yamato_automation.py  (imports: config, models)
    ^
    |  imports services
    |
routers/orders.py        (imports: services)
routers/shipping.py      (imports: services)
    ^
    |  includes routers
    |
main.py                  (FastAPI app assembly)
cli.py                   (CLI entry point, imports services directly)
```

**Forbidden path:** `models/order.py` must NEVER import from `config.py` (circular import).

## Architecture Decisions

1. **Why Playwright?** Yamato Transport doesn't offer a public API. Browser automation is the only option.
2. **Why Both Web and CLI?** Web UI for ad-hoc/interactive use; CLI for reliable scheduled batch processing.
3. **Session Persistence:** Manual login once -> save Playwright `storageState` -> reuse for all automated runs.
4. **Mobile Emulation:** Yamato's smartphone interface (`sp-send.kuronekoyamato.co.jp`) is more automation-friendly than desktop.
5. **Sequential Processing:** Orders processed one-at-a-time to avoid overwhelming Yamato's servers.

## Key Data Models

All defined in `backend/app/models/order.py`:

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `ShopifyOrder` | Unfulfilled order | `order_id`, `order_number`, `shipping_address`, `items`, `package_size` |
| `ShippingResult` | Shipment outcome | `order_id`, `status`, `qr_code_path`, `error_message` |
| `ShippingAddress` | Recipient details | `name`, `postal_code`, `province`, `city`, `address1`, `address2`, `phone` |
| `OrderItem` | Product line item | `title`, `quantity` |
| `PackageSize` | Enum: S, M, L, LL | Determined by total item quantity |
| `ShippingStatus` | Enum: PENDING, PROCESSING, COMPLETED, FAILED | Tracks shipment lifecycle |

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

| Variable | Description | Required |
|----------|-------------|----------|
| `SHOPIFY_STORE_URL` | Shopify store URL | Yes |
| `SHOPIFY_ACCESS_TOKEN` | Shopify Admin API token | Yes |
| `KURONEKO_LOGIN_ID` | Kuroneko Members login ID | Yes |
| `KURONEKO_PASSWORD` | Kuroneko Members password | Yes |
| `SENDER_NAME` | Sender name | Yes |
| `SENDER_POSTAL_CODE` | Sender postal code | Yes |
| `SENDER_ADDRESS1` | Sender address line 1 | Yes |
| `SENDER_ADDRESS2` | Sender address line 2 | No |
| `SENDER_PHONE` | Sender phone number | Yes |
| `HEADLESS_BROWSER` | Headless mode (default: true) | No |
| `AUTH_STATE_PATH` | Auth state file path (default: auth.json) | No |
| `DEFAULT_PACKAGE_SIZE` | Default package size for shipments (default: M) | No |
| `CORS_ALLOWED_ORIGINS` | Allowed origins for CORS (default: localhost:5173,3000) | No |

## Operation Architecture

```text
Development: AI agents (Devin / Claude Code / Gemini) for dev & review
  |
Deploy: Docker image on Mac mini
  |
Execution: cron scheduled or manual `docker compose run`
  |
Monitoring: Log review, error notification
```
