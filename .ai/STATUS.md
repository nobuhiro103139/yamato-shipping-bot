# Development Status

> Current phase: **Phase 2 - Browser Use Integration**
> Last updated: 2026-02-09

## Completed

- [x] Shopify GraphQL API service for fetching unfulfilled orders
- [x] Playwright-based Yamato form automation skeleton (PR #1, #2, #6)
- [x] Docker setup (non-root user, Playwright Chromium bundled)
- [x] CLI (ship/check/health commands)
- [x] PII masking in log outputs
- [x] CORS configuration (env-based)
- [x] Type hints and docstrings
- [x] `.ai/` directory with project context, tips, playbook, and status
- [x] Delivery date/time, notification, address book selection (PR #6)
- [x] Manual shipment creation via Devin browser (3 shipments: 小島, 舩岡, 渡辺)
- [x] Playwright anti-bot detection analysis (headless/headful/CDP all blocked)
- [x] **Browser Use refactoring** - `yamato_agent.py` with LLM-driven automation
- [x] **Shipment model** - `Shipment` class for shipments.json input
- [x] **CLI refactoring** - ship (JSON), ship-shopify (Shopify API), check, health
- [x] **Config update** - LLM provider/model/API key settings
- [x] **Router update** - `/api/shipping/process` accepts Shipment JSON
- [x] **Dependencies** - browser-use, langchain-openai, langchain-anthropic
- [x] **Infrastructure** - Dockerfile, docker-compose.yml updated

## Next TODO (Priority Order)

### High Priority

- [ ] **Mac mini deployment + Browser Use E2E test**
  - **Why:** Browser Use はheadfulモードが前提。Mac miniで実際にヤマトサイトを操作して動作検証が必要
  - Docker image deployment to Mac mini
  - HEADLESS_BROWSER=false で実行
  - shipments.json に1件のテストデータを入れて `python -m app.cli ship` を実行
  - LLM_API_KEY (OpenAI) を設定して動作確認

- [ ] **auth.json セッション管理の自動化**
  - **Why:** Browser Use Agent が自動ログインするが、セッション期限切れ時の再認証フローを検証する必要がある
  - Agent が自動でログインできるか検証
  - セッション永続化の信頼性確認
  - 期限切れ時のgraceful fallback

### Medium Priority

- [ ] **LLM プロンプトチューニング**
  - **Why:** Browser Use の精度はタスクプロンプトの品質に依存する。実サイトでの検証後に改善
  - 実際のヤマトサイトでプロンプトを検証
  - ステップ数・所要時間の最適化
  - エラー時のリトライロジック改善

- [ ] **Slack/Discord 通知**
  - **Why:** バッチ処理の結果を自動通知できると運用が楽になる
  - 処理完了/失敗時の通知
  - Webhook ベースで実装

- [ ] **Frontend (React) completion**
  - **Why:** オペレーターが手動で確認・実行できる UI がないと運用に乗らない
  - Basic components exist but not connected to backend
  - Need: shipment list, ship button, status updates

### Low Priority

- [ ] **Automated tests**
  - **Why:** リグレッション防止。本番安定稼働後に着手
  - Shipment model validation tests
  - CLI integration tests (mock Browser Use)

- [ ] **Shopify → shipments.json 自動変換**
  - **Why:** 現在は ship-shopify コマンドで直接処理するが、JSON経由のパイプラインも有用
  - 別エージェントが Shopify → JSON 変換を担当する想定

## Known Issues

- Browser Use は未テスト（Mac mini headful環境が必要）
- yamato_automation.py (legacy) はアンチボット検知により Devin 環境では動作不可
- Frontend は scaffolded but not functional
- No automated tests exist yet
- Shopify API version `2025-10` は `2026-01` の1つ前だが Oct 2026 までサポート

## Phase Roadmap

1. **Phase 1:** PoC - Playwright direct automation (completed, blocked by anti-bot)
2. **Phase 2 (Current):** Browser Use Integration - LLM-driven automation
3. **Phase 3:** Production - Mac mini deployment, E2E testing, prompt tuning
4. **Phase 4:** Dashboard - React frontend, Slack notifications
5. **Phase 5:** Pipeline - Shopify → JSON → Browser Use fully automated
