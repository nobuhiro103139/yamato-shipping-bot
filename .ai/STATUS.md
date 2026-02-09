# Development Status

> Current phase: **Phase 1 - PoC (Proof of Concept)**
> Last updated: 2026-02-09

## Completed

- [x] Shopify GraphQL API service for fetching unfulfilled orders
- [x] Playwright-based Yamato form automation skeleton
- [x] Docker setup (non-root user, Playwright Chromium bundled)
- [x] CLI (ship/check/health commands)
- [x] PII masking in log outputs
- [x] CORS configuration (env-based)
- [x] Type hints and docstrings
- [x] PR #1 (Docker + CLI) merged
- [x] PR #2 (Code quality improvements) merged
- [x] `.ai/` directory with project context, tips, playbook, and status

## Next TODO (Priority Order)

### High Priority

- [ ] **Yamato form real-site selector verification**
  - **Why:** PoC の成功に必須。セレクタが動かなければ自動化は何も始まらない
  - All CSS selectors in `yamato_automation.py` are best-guess estimates
  - Need to use `playwright codegen --device="iPhone 13"` on the real Yamato site
  - Selectors to verify: postal code input, name fields, address fields, phone input, submit buttons

- [ ] **Shopify API real-environment test**
  - **Why:** データ取得が正しく動くことの検証なしに、下流の自動入力は開発できない
  - Set `SHOPIFY_STORE_URL` and `SHOPIFY_ACCESS_TOKEN` with real credentials
  - Run `python -m app.cli check` to verify order fetching works
  - Validate the GraphQL query response structure
  - Note: Currently using API version `2025-10` (supported until Oct 2026). Latest is `2026-01`.

- [ ] **Kuroneko Members login flow**
  - **Why:** 認証なしではヤマトサイトにアクセスできず、セレクタ検証もできない
  - Test `save_auth_state()` for initial manual login -> auth.json save
  - Verify session persistence across automation runs
  - Handle session expiration gracefully

### Medium Priority

- [ ] **Payment step implementation**
  - **Why:** 現在は決済前のスクリーンショットまで。完全自動化にはこのステップが必要
  - Currently stops at pre-payment screenshot
  - Need to implement: payment button click -> QR code capture
  - Requires real Yamato site testing

- [ ] **Frontend (React) completion**
  - **Why:** オペレーターが手動で確認・実行できる UI がないと運用に乗らない
  - Basic components exist but are not connected to backend
  - Need: order list display, ship button, status updates, QR code viewer

### Low Priority

- [ ] **Mac mini deployment**
  - **Why:** 最終的な本番環境。PoC 完了後に着手
  - Docker image deployment to Mac mini
  - cron job setup for daily 10:00 AM execution
  - Log rotation and monitoring

- [ ] **Error handling improvements**
  - **Why:** 本番運用の安定性向上。PoC 段階では後回し可
  - Retry logic for transient failures
  - Better error messages for common failure modes
  - Email/Slack notification on failure

## Known Issues

- CSS selectors in `yamato_automation.py` are unverified (may not match actual Yamato HTML)
- Frontend is scaffolded but not functional
- No automated tests exist yet
- Shopify API version `2025-10` is one version behind latest (`2026-01`), but still supported until Oct 2026

## Phase Roadmap

1. **Phase 1 (Current):** PoC - Verify automation works end-to-end with real Yamato site
2. **Phase 2:** Production - Complete payment flow, error handling, monitoring
3. **Phase 3:** Dashboard - Finish React frontend, connect to backend APIs
4. **Phase 4:** Deployment - Mac mini setup, cron scheduling, operational monitoring
