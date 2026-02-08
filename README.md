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

## プロジェクト構成

```
yamato-shipping-bot/
├── backend/           # FastAPI バックエンド
│   ├── app/
│   │   ├── main.py           # FastAPI エントリーポイント
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
└── README.md
```

## セットアップ

### バックエンド

```bash
cd backend
cp .env.example .env
# .env を編集して Shopify API キー等を設定

poetry install
poetry add playwright
playwright install chromium

# 開発サーバー起動
poetry run fastapi dev app/main.py
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

## 処理フロー

1. Shopify Admin API (GraphQL) で未発送注文を取得
2. ダッシュボードで注文一覧を表示
3. 「発送する」ボタンクリック
4. Playwright がモバイルエミュレーションでヤマト「スマホで送る」にアクセス
5. フォームに自動入力（お届け先、依頼主、品名、サイズ等）
6. 決済実行 → QR コード取得

## 環境変数

| 変数名 | 説明 |
|--------|------|
| `SHOPIFY_STORE_URL` | Shopify ストア URL |
| `SHOPIFY_ACCESS_TOKEN` | Shopify Admin API アクセストークン |
| `SENDER_NAME` | 依頼主の氏名 |
| `SENDER_POSTAL_CODE` | 依頼主の郵便番号 |
| `SENDER_ADDRESS1` | 依頼主の住所 |
| `SENDER_PHONE` | 依頼主の電話番号 |
| `HEADLESS_BROWSER` | ヘッドレスモード (true/false) |
