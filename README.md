# Yamato Shipping Bot

TechRental の配送自動化システム。Shopify の注文データからヤマト運輸「スマホで送る」のフォームに自動入力し、発送処理を自動化します。

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| ブラウザ自動操作 | Playwright (Python) - モバイルエミュレーション |
| データ取得 | Shopify Admin API (GraphQL) |
| バックエンド | FastAPI |
| フロントエンド | React (Vite + TypeScript + Tailwind CSS) |
| セッション管理 | Playwright storageState |
| シークレット管理 | 1Password CLI (`op run`) |
| コンテナ | Docker / Docker Compose |

## プロジェクト構成

```
yamato-shipping-bot/
├── backend/           # FastAPI バックエンド
│   ├── app/
│   │   ├── main.py           # FastAPI エントリーポイント
│   │   ├── cli.py            # CLI ランナー（バッチ処理用）
│   │   ├── config.py         # 環境設定
│   │   ├── models/           # Pydantic モデル
│   │   ├── routers/          # API ルーター
│   │   └── services/         # ビジネスロジック
│   │       ├── shopify_service.py      # Shopify API 連携
│   │       └── yamato_automation.py    # Playwright 自動操作
│   ├── .env.example
│   └── pyproject.toml
├── frontend/          # React ダッシュボード
│   ├── src/
│   │   ├── App.tsx           # メインコンポーネント
│   │   ├── api.ts            # API クライアント
│   │   ├── types.ts          # 型定義
│   │   └── components/       # UI コンポーネント
│   ├── .env.example
│   └── package.json
├── scripts/           # ユーティリティスクリプト
│   └── entrypoint.sh          # Docker エントリーポイント（op run 連携）
├── Dockerfile         # Docker イメージ定義
├── docker-compose.yml # Docker Compose 設定
├── .dockerignore
└── README.md
```

## クイックスタート（Docker）

### 方法A: 1Password でシークレット管理（推奨）

1Password CLI (`op`) を使って、シークレットをコードや `.env` ファイルに残さず安全に管理できます。

#### 1. 1Password に項目を作成

1Password アプリで `Dev` Vault に以下の3つの項目を作成してください：

| 項目名 | フィールド | 対応する環境変数 |
|--------|-----------|-----------------|
| **Shopify** | `store-url` | `SHOPIFY_STORE_URL` |
| | `access-token` | `SHOPIFY_ACCESS_TOKEN` |
| **Kuroneko Members** | `username` | `KURONEKO_LOGIN_ID` |
| | `password` | `KURONEKO_PASSWORD` |
| **Sender Info** | `name` | `SENDER_NAME` |
| | `postal-code` | `SENDER_POSTAL_CODE` |
| | `address1` | `SENDER_ADDRESS1` |
| | `address2` | `SENDER_ADDRESS2` |
| | `phone` | `SENDER_PHONE` |

#### 2. サービスアカウントトークンを設定

```bash
export OP_SERVICE_ACCOUNT_TOKEN="your-service-account-token"
```

#### 3. Docker で起動

```bash
docker compose up -d backend
docker compose run --rm runner ship
```

`OP_SERVICE_ACCOUNT_TOKEN` が設定されていれば、エントリーポイントが自動的に `op run` で 1Password からシークレットを注入します。

### 方法B: .env ファイルで設定（従来方式）

```bash
cp backend/.env.example backend/.env
# backend/.env を編集して Shopify API キー等を設定
```

### Docker コマンド

```bash
# API サーバー起動
docker compose up -d backend

# バッチ処理（全未発送注文を処理）
docker compose run --rm runner ship

# 未発送注文の確認のみ
docker compose run --rm runner check

# 設定確認
docker compose run --rm runner health
```

### 3. Mac mini での cron 設定例

```bash
# 毎日10時に自動発送処理
0 10 * * * cd /path/to/yamato-shipping-bot && docker compose run --rm runner ship >> /var/log/yamato-bot.log 2>&1
```

## ローカル開発

### バックエンド

```bash
cd backend
cp .env.example .env

poetry install
playwright install chromium

# 開発サーバー起動
poetry run fastapi dev app/main.py

# CLI で直接実行
poetry run python -m app.cli ship
poetry run python -m app.cli check
```

### フロントエンド

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

### 初回認証（クロネコメンバーズ）

バックエンド起動後、以下のエンドポイントを呼び出してブラウザを起動し、手動でログインします：

```bash
curl -X POST http://localhost:8000/api/shipping/init-auth
```

ログイン後、セッション情報が `auth.json` に保存され、以降は自動ログインが可能になります。

## API エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/healthz` | ヘルスチェック |
| GET | `/api/orders/unfulfilled` | 未発送注文一覧取得 |
| POST | `/api/shipping/process` | 発送処理実行 |
| POST | `/api/shipping/init-auth` | クロネコメンバーズ認証初期化 |

## CLI コマンド

| コマンド | 説明 |
|---------|------|
| `python -m app.cli ship` | 全未発送注文を自動発送処理 |
| `python -m app.cli check` | 未発送注文の一覧表示（処理しない） |
| `python -m app.cli health` | 設定状態の確認 |

## 処理フロー

1. Shopify Admin API (GraphQL) で未発送注文を取得
2. ダッシュボードで注文一覧を表示（またはCLIで直接実行）
3. 「発送する」ボタンクリック（またはCLIの `ship` コマンド）
4. Playwright がモバイルエミュレーションでヤマト「スマホで送る」にアクセス
5. フォームに自動入力（お届け先、依頼主、品名、サイズ等）
6. 決済実行 → QR コード取得

## 環境変数

| 変数名 | 説明 |
|--------|------|
| `SHOPIFY_STORE_URL` | Shopify ストア URL |
| `SHOPIFY_ACCESS_TOKEN` | Shopify Admin API アクセストークン |
| `KURONEKO_LOGIN_ID` | クロネコメンバーズ ID |
| `KURONEKO_PASSWORD` | クロネコメンバーズ パスワード |
| `SENDER_NAME` | 依頼主の氏名 |
| `SENDER_POSTAL_CODE` | 依頼主の郵便番号 |
| `SENDER_ADDRESS1` | 依頼主の住所 |
| `SENDER_ADDRESS2` | 依頼主の建物名等 |
| `SENDER_PHONE` | 依頼主の電話番号 |
| `HEADLESS_BROWSER` | ヘッドレスモード (true/false) |
| `AUTH_STATE_PATH` | 認証状態ファイルのパス |
| `OP_SERVICE_ACCOUNT_TOKEN` | 1Password サービスアカウントトークン（任意） |

## 運用アーキテクチャ

```text
開発: Devin で開発・テスト
  ↓
デプロイ: Docker イメージを Mac mini に配置
  ↓
実行: cron で定期実行 or 手動 docker compose run
  ↓
監視: ログ確認、エラー通知
```
