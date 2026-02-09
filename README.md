# Yamato Shipping Bot

TechRental の配送自動化システム。[Browser Use](https://github.com/browser-use/browser-use)（AI エージェント型ブラウザ自動化）でヤマト運輸「スマホで送る」のフォームに自動入力し、発送処理を自動化します。

## アーキテクチャ

```text
[別エージェント/手動] → shipments.json に保存
         ↓
  cron: 毎日AM 9:00
         ↓
  python -m app.cli ship
         ↓
  Browser Use Agent が shipments.json を読む
         ↓
  1件ずつヤマト「スマホで送る」に入力（LLM駆動）
         ↓
  完了ログ出力
```

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| ブラウザ自動操作 | Browser Use (AI Agent) + Playwright |
| LLM | OpenAI GPT-4o (default) / Anthropic Claude |
| データ入力 | shipments.json（整形済みデータ） |
| データ取得（任意） | Shopify Admin API (GraphQL) |
| バックエンド | FastAPI |
| セッション管理 | Playwright storageState (auth.json) |
| コンテナ | Docker / Docker Compose |

## プロジェクト構成

```
yamato-shipping-bot/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI エントリーポイント
│   │   ├── cli.py                # CLI（ship / ship-shopify / check / health）
│   │   ├── config.py             # 環境設定（LLM・ヤマト・Shopify）
│   │   ├── models/
│   │   │   └── order.py          # Shipment, ShopifyOrder, ShippingResult
│   │   ├── routers/
│   │   │   ├── shipping.py       # POST /api/shipping/process
│   │   │   └── orders.py         # GET /api/orders/unfulfilled
│   │   └── services/
│   │       ├── yamato_agent.py   # Browser Use Agent（メイン自動化）
│   │       ├── yamato_automation.py  # (legacy) Playwright直接操作
│   │       └── shopify_service.py    # Shopify API連携
│   ├── shipments.example.json    # 入力データのサンプル
│   ├── .env.example
│   └── pyproject.toml
├── .ai/                   # AI エージェント向けコンテキスト
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## クイックスタート

### 1. 環境変数の設定

```bash
cp backend/.env.example backend/.env
# LLM_API_KEY, KURONEKO_LOGIN_ID, KURONEKO_PASSWORD を設定
```

### 2. shipments.json を準備

```bash
cp backend/shipments.example.json backend/shipments.json
# 発送データを編集
```

`shipments.json` のフォーマット:

```json
[
  {
    "recipient_last_name": "山田",
    "recipient_first_name": "太郎",
    "recipient_postal_code": "150-0001",
    "recipient_phone": "09012345678",
    "recipient_email": "taro@example.com",
    "recipient_chome": "1",
    "recipient_banchi": "2-3",
    "recipient_building": "マンション101",
    "product_name": "スマートフォン",
    "package_size": "compact",
    "shipping_date": "2026-02-15",
    "delivery_date": "2026-02-16",
    "delivery_time": "18:00~20:00"
  }
]
```

### 3. 実行

```bash
cd backend
poetry install
playwright install chromium

# shipments.json から発送処理
poetry run python -m app.cli ship

# Shopify連携モード（要Shopify設定）
poetry run python -m app.cli ship-shopify

# 保留中の発送確認
poetry run python -m app.cli check

# 設定確認
poetry run python -m app.cli health
```

### 4. Docker で実行

```bash
docker compose run --rm runner ship
docker compose run --rm runner check
docker compose run --rm runner health
```

### 5. cron 設定（Mac mini）

```bash
0 9 * * * cd /path/to/yamato-shipping-bot && docker compose run --rm runner ship >> /var/log/yamato-bot.log 2>&1
```

## 初回認証

Browser Use Agent は初回実行時にクロネコメンバーズへ自動ログインします。
認証情報は `auth.json` に保存され、以降はセッション再利用します。

セッション切れの場合は `auth.json` を削除して再実行してください。

## CLI コマンド

| コマンド | 説明 |
|---------|------|
| `python -m app.cli ship` | shipments.json から発送処理（デフォルト） |
| `python -m app.cli ship-shopify` | Shopify API から取得して発送処理 |
| `python -m app.cli check` | 保留中の発送データ一覧 |
| `python -m app.cli health` | 設定状態の確認 |

## API エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/healthz` | ヘルスチェック |
| GET | `/api/orders/unfulfilled` | 未発送注文一覧（Shopify） |
| POST | `/api/shipping/process` | 発送処理実行（Shipment JSON） |

## 環境変数

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `LLM_PROVIDER` | | LLM プロバイダー（openai / anthropic） |
| `LLM_MODEL` | | モデル名（gpt-4o） |
| `LLM_API_KEY` | Yes | LLM API キー |
| `KURONEKO_LOGIN_ID` | Yes | クロネコメンバーズ ID |
| `KURONEKO_PASSWORD` | Yes | クロネコメンバーズ パスワード |
| `SENDER_NAME` | | 依頼主名（アドレス帳検索用） |
| `SHIPMENTS_PATH` | | shipments.json のパス |
| `HEADLESS_BROWSER` | | ヘッドレスモード（Mac mini: false 推奨） |
| `AUTH_STATE_PATH` | | 認証状態ファイルのパス |
| `SHOPIFY_STORE_URL` | | Shopify ストア URL（ship-shopify用） |
| `SHOPIFY_ACCESS_TOKEN` | | Shopify API トークン（ship-shopify用） |

## Browser Use について

[Browser Use](https://github.com/browser-use/browser-use) は AI エージェントがブラウザを操作するフレームワークです。

- LLM が自然言語のタスク指示を理解してフォームを操作
- HTML構造の変更に強い（セレクタ依存しない）
- ヤマトのアンチボット検知を回避しやすい（headful + 通常のブラウザ操作パターン）
- モバイルエミュレーション対応（iPhone UA, 390x844 viewport）

### Playwright 直接操作との比較

| 観点 | Browser Use (AI) | Playwright 直接 |
|------|-----------------|----------------|
| セレクタ変更への耐性 | 高い | 低い（都度修正） |
| アンチボット検知 | 回避しやすい | 検知されやすい |
| 実行速度 | 遅い（LLM推論あり） | 速い |
| コスト | LLM API料金 | 無料 |
| デバッグ | ログ・スクショ | ステップ単位 |
