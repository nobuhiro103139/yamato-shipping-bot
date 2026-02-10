# Development Status

> Current phase: **Phase 1 - PoC (Xvfb + GitHub Actions 検証中)**
> Last updated: 2026-02-10

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
- [x] Delivery date/time, notification, address book selection (PR #6)
- [x] Manual shipment creation via Devin browser (3 shipments completed)
- [x] **Xvfb + headful Playwright 検証** — ヤマトのアンチボット検知を突破できることを確認
- [x] **ヤマトサイトHTML構造の解析** — setAction() メカニズム、画像ボタン構造、フォームBean名を全て特定
- [x] **E2Eテストスクリプト作成** — `scripts/test_e2e_xvfb.py` にXvfb+headful方式のテストを実装

## Next TODO (Priority Order)

### High Priority

- [ ] **E2E一気通貫テスト完走**
  - **Why:** Xvfb方式が全ステップ通るか確認しないと GitHub Actions 案が成立しない
  - ログイン → 発払い → 荷物設定 → 宛先入力 → 確認画面手前まで
  - セレクタは全て判明済み（`scripts/test_e2e_xvfb.py` に実装済み）
  - ログインのレート制限/同時セッション競合に注意（時間を空けて再試行）
  - テストデータ: 大倉愛子 / 〒206-0024 東京都多摩市諏訪1-27-3 / 09029421016

- [ ] **GitHub Actions workflow 実装**
  - **Why:** 案Aの本体。Xvfb + headful Playwright で毎朝自動実行
  - `xvfb-run --auto-servernum` でheadfulブラウザを起動
  - Secrets: YAMATO_USER, YAMATO_PASS
  - cron: 毎朝9:00 JST
  - LINE Notify でQRコードをスマホに送信

- [ ] **リポジトリリファクタ（PROPOSAL.md ベース）**
  - **Why:** 現在のFastAPI/React構成は不要。scripts/ベースにシンプル化
  - Frontend 削除、FastAPI 削除
  - `scripts/ship.py`, `scripts/notify.py` ベースに
  - `yamato_automation.py` と `shopify_service.py` は流用

### Medium Priority

- [ ] **LINE Notify 連携**
  - **Why:** QRコードのスクショをスマホに自動送信
  - LINE Notify API でQR画像を送信
  - GitHub Actions の最終ステップで実行

- [ ] **Shopify → shipments.json 自動変換**
  - **Why:** 別エージェントが Shopify → JSON 変換を担当する想定

### Low Priority

- [ ] **Mac mini フォールバック**
  - **Why:** Xvfb + GitHub Actions でダメだった場合の保険
  - headful モードで実行

## Known Issues

- **ログインリダイレクトが不安定**: auth.kms → sp-send のリダイレクトチェーンが時々タイムアウト（30-60秒）
- **auth.json セッション永続化は不可**: 前回の検証でセッション再利用は失敗。毎回ログインが必要
- **同時セッション競合**: オーナーが手動でヤマトを使用中だとログインが失敗する可能性
- Frontend は scaffolded but not functional（リファクタで削除予定）

## Phase Roadmap

1. **Phase 1 (Current):** Xvfb + GitHub Actions 検証 — E2E通過を確認
2. **Phase 2:** リポジトリリファクタ — scripts/ベースにシンプル化
3. **Phase 3:** GitHub Actions workflow 実装 — cron + LINE Notify
4. **Phase 4:** Production — 毎朝自動実行、エラー通知、運用監視
