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
poetry install
python -m playwright install --with-deps chromium
cp .env.example .env  # Edit with credentials
```

## Anti-Patterns (禁止事項)

These are hard rules. Violating them will break the system.

| Rule | Reason |
|------|--------|
| `scripts/models.py` から `scripts/config.py` をインポートしない | Circular import で起動しなくなる |
| ログに個人情報をマスクなしで出力しない | PII 漏洩。名前は頭文字+`***`、住所は都道府県+市区町村まで |
| 本番の Yamato サイトで深夜にテスト実行しない | メンテナンス時間帯でフォームが応答しない |
| `git push --force` しない | 他のコミットが消える |
| `.env` や `auth.json` をコミットしない | クレデンシャル漏洩 |
| Supabase の service_role key をログ/エラーに出さない | 重大な漏洩 |
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

### Task: Debug Supabase Integration

1. `python -m scripts.ship health` で Supabase が configured になっているか確認
2. `python -m scripts.ship check` で pending rentals が取得できるか確認
3. `scripts/supabase_client.py` の PostgREST クエリ条件を確認（shipping_status / rental_status / shipping_date）

### Task: Debug Yamato Automation

1. `HEADLESS_BROWSER=false` を設定して可視化
2. `.ai/TIPS.md` (tags: `yamato`, `playwright`) で既知の動作を確認
3. `qr_codes/` のスクショ（confirmation / error）で壊れたページを特定
4. selectorが壊れた場合は `playwright codegen --device="iPhone 13" https://sp-send.kuronekoyamato.co.jp/` で再取得

### Task: Update Docker / GitHub Actions

1. `Dockerfile`, `docker-compose.yml`, `.github/workflows/ship.yml` を更新
2. 新しい env var を追加した場合は `.env.example` と `.ai/CONTEXT.md` も必ず更新

## Code Quality Checklist

Before creating a PR, verify:

- [ ] Type hints on all function signatures
- [ ] Docstrings on public functions
- [ ] PII masking in any new log outputs
- [ ] No circular imports (`models.py` -> `config.py`)
- [ ] New env vars added to `.env.example` and `.ai/CONTEXT.md`
- [ ] `.ai/STATUS.md` updated
- [ ] `.ai/TIPS.md` appended (if new discoveries)

## File Modification Guide

| What to change | Where |
|----------------|-------|
| Yamato form automation | `scripts/yamato_automation.py` |
| Supabase data fetch/update | `scripts/supabase_client.py` |
| Data models | `scripts/models.py` |
| Configuration | `scripts/config.py` + `.env.example` |
| CLI commands | `scripts/ship.py` |
| Docker setup | `Dockerfile` + `docker-compose.yml` |
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
- **Gemini:** The structured Markdown format is optimized for LLM parsing. Each file is self-contained.
- **Cursor / Copilot:** Point your project rules or `.cursorrules` to read `.ai/CONTEXT.md` on session start.
- **Any agent:** The tag system in TIPS.md enables targeted retrieval. Search for specific tags (e.g., `yamato`, `selector`) to find relevant tips quickly.

## .ai/ Documentation Maintenance Protocol

This `.ai/` directory is only useful if it stays in sync with reality.
The goal is **骨太な方針（core decisions）を正確に保つ** - not to update on every small change.

### When to Update Each File

| File | Update trigger | Examples |
|------|---------------|----------|
| `CONTEXT.md` | Architecture or core decisions change | New service added, tech stack changed, new API endpoint, env var added, import structure changed |
| `STATUS.md` | Every PR (always) | Task completed, new task discovered, priority changed, phase transition |
| `TIPS.md` | New discovery during development | Selector found, Yamato behavior observed, gotcha encountered |
| `PLAYBOOK.md` | Workflow or rules change | New anti-pattern discovered, new task type needed, tooling changed |

### What NOT to Update

- Don't update CONTEXT.md for bug fixes or minor refactors
- Don't update PLAYBOOK.md for one-off workarounds
- Don't rewrite TIPS.md entries - only append new ones (exception: fix factually wrong information with a `[Corrected YYYY-MM-DD]` note)

### Owner Decision Changes

When the project owner communicates a change in direction (e.g., new priority, dropped feature, different deployment target):

1. Update `STATUS.md` priorities and **Why** explanations to reflect the new direction
2. If the change affects architecture (e.g., "we're switching from Mac mini to cloud"), update `CONTEXT.md`
3. Add a dated tip to `TIPS.md` documenting the decision change for future context

## After Completing Work

1. Update `.ai/STATUS.md`:
   - Move completed items from "Next TODO" to "Completed"
   - Add any new discovered tasks to "Next TODO" with a **Why** explanation
   - Update the "Last Updated" date
2. Append any new discoveries to `.ai/TIPS.md` with appropriate tags
3. If you changed architecture, env vars, or core decisions, update `.ai/CONTEXT.md`
4. Create a PR with clear description of changes
