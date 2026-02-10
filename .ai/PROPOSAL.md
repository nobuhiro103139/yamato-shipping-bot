# ヤマト「スマホで送る」自動化 — アーキテクチャ提案

## 前提条件

- TechRentalのShopifyストアから毎日発送がある
- **コンビニ発送**のためQRコードが必要 → 「スマホで送る」を使う必要がある
- ヤマトB2クラウドはコンビニ発送非対応のため現時点では使えない
- Mac miniに常駐させたくない（他の用途に使う可能性がある）
- 将来的に規模拡大したらB2クラウドに移行する可能性はある

## 現状の問題

現在のコードはFastAPI + React + Playwrightで構成されているが、やりたいことに対してオーバーエンジニアリングになっている。

- React管理画面 → 不要（QRコードが手元に届けばいい）
- FastAPIサーバー → 不要（常駐サーバーは要らない）
- Docker Compose（backend + runner） → 過剰

本当に必要なのは：
1. Shopifyから未発送注文を取得する
2. ヤマト「スマホで送る」を自動操作してQRコードを発行する
3. QRコード画像を自分のスマホに届ける（LINE等）
4. これを毎日自動で動かす

## 選択肢

### 案A: GitHub Actions + LINE Notify（推奨）

**概要**: GitHub Actionsのscheduleトリガーで毎日実行。QRコードをLINE Notifyで送信。

**構成**:
```
.github/workflows/ship.yml  (cronスケジュール)
scripts/
  ship.py                   (メインスクリプト)
  shopify_client.py          (Shopify API連携 ← 既存コード流用)
  yamato_automation.py       (Playwright自動操作 ← 既存コード流用)
  notify.py                  (LINE Notify送信)
```

**メリット**:
- 無料（GitHub Actionsの無料枠: 2,000分/月）
- サーバー管理不要
- Mac mini不要
- コードがシンプル（フロントエンド・API不要）
- GitHub上でログが見れる
- 手動トリガーも可能（workflow_dispatch）

**デメリット**:
- GitHub Actionsのランナーは毎回クリーンなので、ヤマトのログインセッション（auth.json）を永続化する工夫が必要（GitHub Secrets or Artifactで対応可能）
- Playwrightのインストールに1-2分かかる（キャッシュで軽減可能）

**セッション管理の方法**:
- auth.jsonをGitHub Actionsのartifactとして保存し、次回実行時にダウンロード
- セッション切れ時はLINEで通知 →手動で再ログインしてauth.jsonを更新

### 案B: クラウドVM（Railway / Fly.io / Render）

**概要**: Dockerコンテナをクラウドにデプロイし、cronジョブで実行。

**構成**: 現在のDocker構成をほぼそのまま使用（フロントエンド削除）

**メリット**:
- 環境が永続的（auth.jsonの管理が楽）
- 今のDockerfileがそのまま使える

**デメリット**:
- 月額$5-7程度のコストがかかる
- サーバーの管理が必要（落ちてないか監視）
- このユースケースには過剰

### 案C: Mac miniでcron実行

**概要**: Mac miniにDockerをインストールし、cronで毎日実行。

**メリット**:
- 既に手元にある
- 環境が永続的

**デメリット**:
- Mac miniを他の用途に使いたい
- Mac miniが落ちてたら発送されない
- 自宅ネットワークに依存

### 案D: AIエージェント（Manus等）に毎回やらせる

**概要**: ManusやDevinのブラウザ機能で毎日手動 or 自動実行。

**メリット**:
- コードを書かなくていい

**デメリット**:
- 1回あたり数百〜数千円のコスト（月数万円になる可能性）
- AIが住所を間違えるリスクがある
- 毎回プロンプトを書く or 自動化の仕組みが別途必要
- 本末転倒（自動化のために高コストのAIを使う）

## 推奨: 案A（GitHub Actions + LINE Notify）

理由:
1. **コスト$0** — 毎日1回の実行なら無料枠に余裕で収まる
2. **メンテナンスフリー** — サーバー管理不要
3. **既存コード流用** — shopify_service.pyとyamato_automation.pyのコアロジックはそのまま使える
4. **シンプル** — React/FastAPIを削除してスクリプト1本にまとめられる
5. **柔軟** — GitHub UIから手動実行もできる、cronの時間変更も簡単

## 推奨案の実装計画

### 削除するもの
- `frontend/` ディレクトリ全体
- `backend/app/routers/` （FastAPIルーター）
- `backend/app/main.py` （FastAPIサーバー）
- `docker-compose.yml` （ローカル実行用）
- `Dockerfile` （GitHub Actionsでは不要）

### 残すもの（リファクタ）
- `shopify_service.py` → `scripts/shopify_client.py`
- `yamato_automation.py` → `scripts/yamato_automation.py`
- `models/order.py` → `scripts/models.py`
- `config.py` → 環境変数から直接読む（簡素化）

### 新規作成
- `.github/workflows/ship.yml` — cronスケジュール + 手動トリガー
- `scripts/ship.py` — メインエントリーポイント
- `scripts/notify.py` — LINE Notify連携
- `scripts/session_manager.py` — auth.jsonのartifact管理

### GitHub Actionsワークフロー（イメージ）
```yaml
name: Daily Shipping
on:
  schedule:
    - cron: '0 1 * * *'  # 毎日10:00 JST
  workflow_dispatch:       # 手動実行も可能

jobs:
  ship:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install playwright httpx pydantic-settings requests

      - name: Install Playwright browsers
        run: playwright install chromium --with-deps

      - name: Download auth session
        uses: actions/download-artifact@v4
        with:
          name: yamato-auth
        continue-on-error: true  # 初回は存在しない

      - name: Run shipping automation
        env:
          SHOPIFY_STORE_URL: ${{ secrets.SHOPIFY_STORE_URL }}
          SHOPIFY_ACCESS_TOKEN: ${{ secrets.SHOPIFY_ACCESS_TOKEN }}
          LINE_NOTIFY_TOKEN: ${{ secrets.LINE_NOTIFY_TOKEN }}
        run: python scripts/ship.py

      - name: Save auth session
        uses: actions/upload-artifact@v4
        with:
          name: yamato-auth
          path: auth.json
          retention-days: 90
```

## 次のステップ

1. 現在のリポジトリ構造をスクリプトベースにリファクタ
2. GitHub Actionsワークフローを作成
3. LINE Notify連携を実装
4. セッション管理（auth.json永続化）を実装
5. テスト実行（Shopify sandbox + ヤマト実サイト）
