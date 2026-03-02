# Development Status

> Current phase: **Phase 1 - PoC (Proof of Concept)**
> Last updated: 2026-03-02

## Completed

- [x] Playwright-based Yamato form automation (mobile emulation)
- [x] Docker setup (Playwright Chromium bundled)
- [x] CLI (ship/check/health commands)
- [x] PII masking in log outputs (names masked)
- [x] GitHub Actions daily run workflow
- [x] **Supabase (techrental-core) 直結に切り替え（rentals/customers を source of truth に変更）**
  - Shopify API 経由の取得を廃止（`shopify_client.py` 削除）
  - `supabase_client.py` 新規作成（PostgREST fetch + shipping_status update）
  - 成功時に `rentals.shipping_status = shipped` を自動更新
  - **Why:** TechRental-ops で既に Shopify webhook → Supabase 同期が動いており、DB に全データが揃っていた。Shopify API を直接叩くのは冗長だった。

## Next TODO (Priority Order)

### High Priority

- [ ] **Yamatoサイトの実動作確認（Mac mini）**
  - **Why:** Playwrightの自動化はサイト側の変更で壊れる。PoC成立の必須条件
  - 直近の発送対象を1件だけで試す（夜間は避ける）

- [ ] **決済ステップ実装**
  - **Why:** 現状は「下書き保存＋確認画面スクショ」まで。完全自動化には決済→QR取得が必要

- [ ] **Supabase更新の整合性強化**
  - **Why:** 二重発送や誤更新を防ぐ
  - `shipped` 更新時に `rental_status` / `shipping_date` 等の条件を追加検討

### Medium Priority

- [ ] **shipping_status='ready_to_ship' の運用整理**
  - **Why:** OPS側の状態遷移と bot の抽出条件を一致させる

- [ ] **失敗時のリトライ/隔離**
  - **Why:** 運用安定化（同一注文での無限リトライ回避）

### Low Priority

- [ ] **Mac mini デプロイ手順の固定化**
  - **Why:** 本番の最終形。Docker/cron/ログ管理を確立

## Known Issues

- 決済ステップ未実装（下書き保存で停止）
- 自動テストなし
- CSS selectors は実サイト検証済みだが、ヤマト側の変更で壊れる可能性あり

## Phase Roadmap

1. **Phase 1 (Current):** PoC - Supabase連携完了、実サイトでのE2E検証（進行中）
2. **Phase 2:** Production - 決済フロー完成、エラーハンドリング、監視
3. **Phase 3:** Deployment - Mac mini本番運用、cron、ログローテーション
