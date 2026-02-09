# yamato-shipping-bot Project Context

> This file is the single source of truth for AI agents working on this project.
> Read this first to understand the project's purpose, architecture, and current state.

## Project Overview

**Repository:** https://github.com/nobuhiro103139/yamato-shipping-bot
**Owner:** @nobuhiro103139 (TechRental)
**Purpose:** TechRental の配送自動化システム。整形済みの発送データ（shipments.json）を [Browser Use](https://github.com/browser-use/browser-use)（AIエージェント型ブラウザ自動化）で読み込み、ヤマト運輸「宅急便をスマホで送る」(https://sp-send.kuronekoyamato.co.jp/) のWebフォームにLLM駆動で自動入力する。

## Business Background

- TechRental はレンタル機器の配送でヤマト運輸を使っている
- B2 クラウドは契約/コスト面で利用不可
- 「スマホで送る」の Web 版をモバイルエミュレーションで操作する方式を採用
- 手作業をゼロにしたい。Docker 一発で動く形を要求
- ユースケースは「整形済みデータ → 1日1回バッチ → ブラウザ操作」なので Browser Use が最適
- Playwright 直接操作はヤマトのアンチボット検知で失敗（headless不可、CDPも不可）

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Browser Automation | **Browser Use** (AI Agent) + Playwright |
| LLM | OpenAI GPT-4o (default) / Anthropic Claude |
| Data Input | shipments.json (整形済みデータ) |
| Data Source (optional) | Shopify Admin API (GraphQL, version 2025-10) |
| Backend | FastAPI (Python 3.12, Poetry) |
| Frontend | React (Vite + TypeScript + Tailwind CSS) |
| Session Management | Playwright storageState (auth.json) |
| Container | Docker / Docker Compose |

## Project Structure

```text
yamato-shipping-bot/
├── .ai/                         # AI agent context (you are here)
│   ├── README.md                # Directory guide and reading order
│   ├── CONTEXT.md               # Project overview (this file)
│   ├── STATUS.md                # Development status and TODOs
│   ├── TIPS.md                  # Accumulated development tips
│   └── PLAYBOOK.md              # Agent playbook and workflows
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry point (CORS configurable)
│   │   ├── cli.py               # CLI runner (ship/ship-shopify/check/health)
│   │   ├── config.py            # pydantic-settings (env vars, LLM config)
│   │   ├── __main__.py          # CLI entry point
│   │   ├── models/
│   │   │   └── order.py         # Shipment, ShopifyOrder, ShippingResult, etc.
│   │   ├── routers/
│   │   │   ├── orders.py        # GET /api/orders/unfulfilled
│   │   │   └── shipping.py      # POST /api/shipping/process
│   │   └── services/
│   │       ├── yamato_agent.py       # Browser Use Agent (core automation)
│   │       ├── yamato_automation.py  # (legacy) Playwright direct automation
│   │       └── shopify_service.py    # Shopify GraphQL API integration
│   ├── shipments.example.json   # Input data sample
│   ├── .env.example
│   └── pyproject.toml
├── frontend/
│   └── src/
│       ├── App.tsx              # Main application component
│       ├── api.ts               # Backend API client
│       ├── types.ts             # TypeScript type definitions
│       └── components/          # UI components
├── Dockerfile                   # Python 3.12-slim + Browser Use + Playwright
├── docker-compose.yml           # backend (API) + runner (CLI) services
└── README.md
```

## Import Dependency Graph

Understanding the import chain is critical to avoid circular imports.

```text
models/order.py          (defines: PackageSize, Shipment, ShopifyOrder, ShippingResult, etc.)
    ^
    |  imports PackageSize, Shipment, ShippingResult
    |
config.py                (defines: Settings, get_settings)
    ^
    |  imports get_settings, Settings
    |
services/yamato_agent.py       (imports: config, models; lazy-imports: browser_use, langchain)
services/shopify_service.py    (imports: config, models)
services/yamato_automation.py  (legacy, imports: config, models)
    ^
    |  imports services
    |
routers/orders.py        (imports: shopify_service)
routers/shipping.py      (imports: yamato_agent, models)
    ^
    |  includes routers
    |
main.py                  (FastAPI app assembly)
cli.py                   (CLI entry point, imports yamato_agent directly)
```

**Forbidden path:** `models/order.py` must NEVER import from `config.py` (circular import).

## Architecture Decisions

1. **Why Browser Use?** Yamato detects headless Playwright and blocks sessions. Browser Use's LLM-driven approach is resilient to anti-bot detection and HTML structure changes.
2. **Why not Playwright direct?** Headless blocked by anti-bot. Headful requires display (Mac mini only). CSS selectors break when Yamato updates HTML.
3. **Why not OpenClaw?** Overkill for "1 day / 1 batch" use case. Gateway常時稼働が不要。
4. **Why Both Web and CLI?** Web UI for ad-hoc/interactive use; CLI for reliable scheduled batch processing.
5. **Session Persistence:** auth.json stores Playwright storageState. Browser Use agent auto-logs in if session expired.
6. **Mobile Emulation:** Yamato's smartphone interface is more automation-friendly than desktop. iPhone UA + 390x844 viewport.
7. **Sequential Processing:** Shipments processed one-at-a-time to avoid overwhelming Yamato's servers.
8. **LLM Provider Flexibility:** Supports OpenAI (default) and Anthropic via langchain abstraction.

## Key Data Models

All defined in `backend/app/models/order.py`:

| Model | Purpose | Key Fields |
|-------|---------|------------|
| `Shipment` | **Primary input** from shipments.json | `recipient_last_name`, `postal_code`, `phone`, `email`, `package_size`, `delivery_date` |
| `ShopifyOrder` | Unfulfilled Shopify order | `order_id`, `order_number`, `shipping_address`, `items`, `package_size` |
| `ShippingResult` | Shipment processing outcome | `order_id`, `status`, `qr_code_path`, `error_message` |
| `ShippingAddress` | Recipient details (Shopify) | `last_name`, `first_name`, `postal_code`, `province`, `city`, `phone` |
| `PackageSize` | Enum: COMPACT, S, M, L, LL | Package size category |
| `ShippingStatus` | Enum: PENDING, PROCESSING, COMPLETED, FAILED | Shipment lifecycle state |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Health check |
| GET | `/api/orders/unfulfilled` | Fetch unfulfilled orders from Shopify |
| POST | `/api/shipping/process` | Process single shipment (accepts Shipment JSON) |

## CLI Commands

| Command | Description |
|---------|-------------|
| `python -m app.cli ship` | Process shipments from shipments.json (default) |
| `python -m app.cli ship-shopify` | Fetch from Shopify API and process |
| `python -m app.cli check` | List pending shipments (dry run) |
| `python -m app.cli health` | Display configuration status |

## Required Secrets / Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `LLM_API_KEY` | OpenAI or Anthropic API key | Yes |
| `LLM_PROVIDER` | LLM provider: openai / anthropic (default: openai) | No |
| `LLM_MODEL` | LLM model name (default: gpt-4o) | No |
| `KURONEKO_LOGIN_ID` | Kuroneko Members login ID | Yes |
| `KURONEKO_PASSWORD` | Kuroneko Members password | Yes |
| `SENDER_NAME` | Sender name (address book search) | No |
| `SHIPMENTS_PATH` | Path to shipments.json (default: shipments.json) | No |
| `HEADLESS_BROWSER` | Headless mode (default: false, Mac mini: false) | No |
| `AUTH_STATE_PATH` | Auth state file path (default: auth.json) | No |
| `SHOPIFY_STORE_URL` | Shopify store URL (for ship-shopify) | No |
| `SHOPIFY_ACCESS_TOKEN` | Shopify Admin API token (for ship-shopify) | No |
| `DEFAULT_PACKAGE_SIZE` | Default package size (default: M) | No |
| `CORS_ALLOWED_ORIGINS` | CORS allowed origins (default: localhost:5173,3000) | No |

## Operation Architecture

```text
[Upstream Agent / Manual] → shipments.json
         ↓
  cron: Daily AM 9:00
         ↓
  python -m app.cli ship
         ↓
  Browser Use Agent reads shipments.json
         ↓
  LLM drives form filling on Yamato (1 shipment at a time)
         ↓
  Completion log output
```

```text
Development: AI agents (Devin / Claude Code / Gemini) for dev & review
  |
Deploy: Docker image on Mac mini (headful mode)
  |
Execution: cron scheduled or manual `docker compose run`
  |
Monitoring: Log review, error notification
```
