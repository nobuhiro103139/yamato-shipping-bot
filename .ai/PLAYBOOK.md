# Devin Playbook - yamato-shipping-bot

> This playbook is designed for Devin's scheduled execution.
> It provides step-by-step instructions for common development tasks.

## Quick Start for AI Agents

1. **Read `.ai/CONTEXT.md`** first to understand the project
2. **Read `.ai/STATUS.md`** to see current development state and next tasks
3. **Read `.ai/TIPS.md`** for known gotchas and discoveries
4. After completing work, **update `.ai/STATUS.md`** and **append to `.ai/TIPS.md`**

## Repository Setup

```bash
cd backend
poetry install
poetry run playwright install chromium
cp .env.example .env  # Edit with credentials
```

## Common Tasks

### Task: Fix Failing Automation Selectors

1. Check `.ai/TIPS.md` for known selector issues
2. Navigate to `backend/app/services/yamato_automation.py`
3. Identify the failing selector
4. Use `playwright codegen --device="iPhone 13" https://sp-send.kuronekoyamato.co.jp/` to find correct selectors
5. Update the selector in `yamato_automation.py`
6. Add a tip entry to `.ai/TIPS.md` documenting the correct selector
7. Update `.ai/STATUS.md` if this resolves a known issue

### Task: Add New Feature

1. Read `.ai/CONTEXT.md` for architecture overview
2. Check `.ai/STATUS.md` for related pending tasks
3. Follow existing code patterns:
   - Models go in `backend/app/models/`
   - Business logic goes in `backend/app/services/`
   - API endpoints go in `backend/app/routers/`
   - Config goes in `backend/app/config.py`
4. Maintain PII masking in any new log output
5. Update `.ai/STATUS.md` with progress
6. Add any discoveries to `.ai/TIPS.md`

### Task: Debug Shopify Integration

1. Check `SHOPIFY_STORE_URL` and `SHOPIFY_ACCESS_TOKEN` are set
2. Run `poetry run python -m app.cli health` to verify config
3. Run `poetry run python -m app.cli check` to test order fetching
4. Check `backend/app/services/shopify_service.py` for the GraphQL query
5. Verify API version matches Shopify's current supported versions

### Task: Debug Yamato Automation

1. Set `HEADLESS_BROWSER=false` for visible browser
2. Check `.ai/TIPS.md` for known Yamato site behaviors
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
- [ ] No imports of `config.py` from `models/order.py` (circular import risk)
- [ ] New environment variables added to `.env.example` and `CONTEXT.md`
- [ ] Any new tips added to `.ai/TIPS.md`
- [ ] `.ai/STATUS.md` updated with progress

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
   ```
   ### [YYYY-MM-DD] Brief title
   Description with relevant details, code snippets, or links.
   ```
4. Commit the tip update along with your other changes

## After Completing Work

1. Update `.ai/STATUS.md`:
   - Move completed items from "Next TODO" to "Completed"
   - Add any new discovered tasks to "Next TODO"
   - Update the "Last Updated" date
2. Append any new discoveries to `.ai/TIPS.md`
3. Create a PR with clear description of changes
