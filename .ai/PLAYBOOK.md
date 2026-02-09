# Devin Playbook - yamato-shipping-bot

> This playbook is designed for AI agent scheduled execution (Devin, Claude Code, Gemini, etc.).
> It provides step-by-step instructions, guardrails, and protocols for safe, effective development.

## Quick Start for AI Agents

1. **Read `.ai/CONTEXT.md`** - Project overview, architecture, import graph
2. **Read `.ai/STATUS.md`** - Current state, what's done, what's next (and why)
3. **Read `.ai/TIPS.md`** - Known gotchas, discoveries, searchable by tags
4. After completing work, **update `.ai/STATUS.md`** and **append to `.ai/TIPS.md`**

## Repository Setup

```bash
cd backend
poetry install
poetry run playwright install chromium
cp .env.example .env  # Edit with credentials
```

## Anti-Patterns (禁止事項)

These are hard rules. Violating them will break the system.

| Rule | Reason |
|------|--------|
| `models/order.py` から `config.py` をインポートしない | Circular import でアプリが起動しなくなる |
| ログに個人情報をマスクなしで出力しない | PII 漏洩。名前は頭文字+`***`、住所は都道府県+市区町村まで |
| 本番の Yamato サイトで深夜にテスト実行しない | メンテナンス時間帯でフォームが応答しない |
| `git push --force` しない | 他のコミットが消える |
| `.env` や `auth.json` をコミットしない | クレデンシャル漏洩 |
| Playwright セレクタを検証なしで本番投入しない | Yamato の HTML は予告なく変わる |
| `CORS_ALLOWED_ORIGINS` に `*` を設定しない | セキュリティリスク |

## Common Tasks

### Task: Fix Failing Automation Selectors

1. Check `.ai/TIPS.md` (tag: `selector`) for known selector issues
2. Navigate to `backend/app/services/yamato_automation.py`
3. Identify the failing selector
4. Use `playwright codegen --device="iPhone 13" https://sp-send.kuronekoyamato.co.jp/` to find correct selectors
5. Update the selector in `yamato_automation.py`
6. Add a tip entry to `.ai/TIPS.md` documenting the correct selector
7. Update `.ai/STATUS.md` if this resolves a known issue

### Task: Add New Feature

1. Read `.ai/CONTEXT.md` for architecture overview and import dependency graph
2. Check `.ai/STATUS.md` for related pending tasks
3. Follow existing code patterns:
   - Models go in `backend/app/models/`
   - Business logic goes in `backend/app/services/`
   - API endpoints go in `backend/app/routers/`
   - Config goes in `backend/app/config.py`
4. Maintain PII masking in any new log output
5. Verify no circular imports are introduced (check dependency graph in CONTEXT.md)
6. Update `.ai/STATUS.md` with progress
7. Add any discoveries to `.ai/TIPS.md`

### Task: Debug Shopify Integration

1. Check `SHOPIFY_STORE_URL` and `SHOPIFY_ACCESS_TOKEN` are set
2. Run `poetry run python -m app.cli health` to verify config
3. Run `poetry run python -m app.cli check` to test order fetching
4. Check `backend/app/services/shopify_service.py` for the GraphQL query
5. Verify API version matches Shopify's current supported versions (see TIPS.md tag: `shopify`, `version`)

### Task: Debug Yamato Automation

1. Set `HEADLESS_BROWSER=false` for visible browser
2. Check `.ai/TIPS.md` (tags: `yamato`, `playwright`) for known behaviors
3. Run with a single test order first
4. Check `qr_codes/` directory for screenshots (confirmation or error)
5. If selectors fail, refer to "Fix Failing Automation Selectors" task above

### Task: Update Docker Configuration

1. Read `Dockerfile` and `docker-compose.yml`
2. The `backend` service runs the API server (port 8000)
3. The `runner` service runs CLI commands
4. Both share `yamato-data` and `yamato-qrcodes` volumes
5. Test with `docker compose build` before pushing

## Code Quality Checklist

Before creating a PR, verify:

- [ ] Type hints on all function signatures
- [ ] Docstrings on public functions
- [ ] PII masking in any new log outputs
- [ ] No circular imports introduced (check `.ai/CONTEXT.md` dependency graph)
- [ ] New environment variables added to `.env.example` and `.ai/CONTEXT.md`
- [ ] Any new tips added to `.ai/TIPS.md` with appropriate tags
- [ ] `.ai/STATUS.md` updated with progress
- [ ] Anti-patterns checklist reviewed (see above)

## File Modification Guide

| What to change | Where |
|----------------|-------|
| Yamato form automation | `backend/app/services/yamato_automation.py` |
| Shopify data fetching | `backend/app/services/shopify_service.py` |
| Data models | `backend/app/models/order.py` |
| API endpoints | `backend/app/routers/` |
| Configuration | `backend/app/config.py` + `.env.example` |
| CLI commands | `backend/app/cli.py` |
| Docker setup | `Dockerfile` + `docker-compose.yml` |
| Frontend UI | `frontend/src/` |
| AI context | `.ai/CONTEXT.md` |
| Development tips | `.ai/TIPS.md` |
| Development status | `.ai/STATUS.md` |

## Tips Accumulation Protocol

When you discover something new during development:

1. Open `.ai/TIPS.md`
2. Find the appropriate category section (or create a new one)
3. Add an entry with the format:
   ```markdown
   ### [YYYY-MM-DD] Brief title
   **Tags:** `tag1`, `tag2`, `tag3`
   Description with relevant details, code snippets, or links.
   ```
4. Commit the tip update along with your other changes

## For Claude Code / Gemini / Other AI Agents

This `.ai/` directory is designed to be agent-agnostic. If you're using a different AI tool:

- **Claude Code:** Use `.ai/CONTEXT.md` as your primary knowledge source. You can reference it in your system prompt or CLAUDE.md.
- **Gemini:** The structured markdown format is optimized for LLM parsing. Each file is self-contained.
- **Cursor / Copilot:** Point your project rules or `.cursorrules` to read `.ai/CONTEXT.md` on session start.
- **Any agent:** The tag system in TIPS.md enables targeted retrieval. Search for specific tags (e.g., `yamato`, `selector`) to find relevant tips quickly.

## After Completing Work

1. Update `.ai/STATUS.md`:
   - Move completed items from "Next TODO" to "Completed"
   - Add any new discovered tasks to "Next TODO" with a **Why** explanation
   - Update the "Last Updated" date
2. Append any new discoveries to `.ai/TIPS.md` with appropriate tags
3. Create a PR with clear description of changes
