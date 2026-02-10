# Yamato Shipping Bot

TechRental の配送自動化システム。Shopify の注文データからヤマト運輸「スマホで送る」のフォームに自動入力し、発送処理を自動化します。

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| ブラウザ自動操作 | Playwright (Python) + Xvfb (headful) |
| データ取得 | Shopify Admin API (GraphQL) |
| 通知 | LINE Notify (QRコード画像送信) |
| 実行環境 | GitHub Actions (cron) / Docker |

## プロジェクト構成

```text
yamato-shipping-bot/
├── scripts/                    # メインコード
│   ├── ship.py                 # エントリーポイント (ship/check/health)
│   ├── yamato_automation.py    # Playwright 自動操作
│   ├── shopify_client.py       # Shopify API 連携
│   ├── notify.py               # LINE Notify 連携
│   ├── models.py               # Pydantic モデル
│   └── config.py               # 環境設定
├── .github/workflows/
│   └── ship.yml                # 毎日10:00 JST 自動実行
├── Dockerfile                  # Docker イメージ (Xvfb付き)
├── docker-compose.yml          # ローカル実行用
├── pyproject.toml              # Poetry 依存管理
├── .env.example                # 環境変数テンプレート
└── README.md
```

## クイックスタート

### 1. 環境変数の設定

```bash
cp .env.example .env
# .env を編集して各種認証情報を設定
```

### 2. CLI で実行

```bash
poetry install
python -m playwright install --with-deps chromium

# Xvfb付きで発送処理を実行
xvfb-run --auto-servernum --server-args="-screen 0 1280x960x24" \
  python -m scripts.ship

# 未発送注文の確認のみ
python -m scripts.ship check

# 設定確認
python -m scripts.ship health
```

### 3. Docker で実行

```bash
# バッチ処理（全未発送注文を処理）
docker compose run --rm runner ship

# 未発送注文の確認のみ
docker compose run --rm runner check
```

### 4. GitHub Actions (自動実行)

GitHub Secrets に以下を設定すれば毎日 10:00 JST に自動実行されます:
- `SHOPIFY_STORE_URL`, `SHOPIFY_ACCESS_TOKEN`
- `KURONEKO_LOGIN_ID`, `KURONEKO_PASSWORD`
- `SENDER_NAME`
- `SENDER_POSTAL_CODE`, `SENDER_ADDRESS1`, `SENDER_ADDRESS2` (任意), `SENDER_PHONE`
- `DEFAULT_PACKAGE_SIZE` (任意, デフォルト: M)
- `LINE_NOTIFY_TOKEN`

手動実行: Actions タブ > "Daily Shipping" > "Run workflow"

## CLI コマンド

| コマンド | 説明 |
|---------|------|
| `python -m scripts.ship` | 全未発送注文を自動発送処理 (デフォルト) |
| `python -m scripts.ship check` | 未発送注文の一覧表示 |
| `python -m scripts.ship health` | 設定状態の確認 |

## 処理フロー

1. Shopify Admin API (GraphQL) で未発送注文を取得
2. Playwright が Xvfb + headful モードでヤマト「スマホで送る」にアクセス
3. 毎回フレッシュログイン (クロネコメンバーズ SSO)
4. フォームに自動入力 (お届け先、依頼主、品名、サイズ、配達日時)
5. 下書き保存 + 確認画面スクリーンショット
6. LINE Notify で QRコード画像をスマホに送信

## 環境変数

| 変数名 | 説明 |
|--------|------|
| `SHOPIFY_STORE_URL` | Shopify ストア URL |
| `SHOPIFY_ACCESS_TOKEN` | Shopify Admin API アクセストークン |
| `KURONEKO_LOGIN_ID` | クロネコメンバーズ ID |
| `KURONEKO_PASSWORD` | クロネコメンバーズ パスワード |
| `SENDER_NAME` | 依頼主の氏名 (アドレス帳検索用) |
| `SENDER_POSTAL_CODE` | 依頼主の郵便番号 |
| `SENDER_ADDRESS1` | 依頼主の住所 |
| `SENDER_ADDRESS2` | 依頼主の建物名等 |
| `SENDER_PHONE` | 依頼主の電話番号 |
| `DEFAULT_PACKAGE_SIZE` | デフォルト荷物サイズ (S/M/L/LL) |
| `LINE_NOTIFY_TOKEN` | LINE Notify アクセストークン |

## 運用アーキテクチャ

```text
Shopify (未発送注文)
  ↓
GitHub Actions (毎日 10:00 JST cron)
  ↓
Playwright + Xvfb (ヤマト「スマホで送る」自動操作)
  ↓
LINE Notify (QRコード画像をスマホへ送信)
  ↓
コンビニでQRコードを提示して発送
```
