# Yamato Shipping Bot

TechRental の配送自動化システム。Shopify / Supabase からデータを取得し、ヤマト運輸「スマホで送る」フォームへ Playwright で自動入力 → 下書き保存 → QR コード通知まで行います。

## 前提条件

| 項目 | バージョン |
|------|-----------|
| Python | 3.12+ |
| パッケージマネージャ | [uv](https://docs.astral.sh/uv/) (推奨) または poetry |
| ブラウザ | Chromium (Playwright が自動インストール) |
| OS | macOS / Linux (GitHub Actions は Ubuntu) |

## セットアップ (他 PC 向け)

```bash
# 1. リポジトリ取得
git clone git@github.com:nobuhiro103139/yamato-shipping-bot.git
cd yamato-shipping-bot

# 2. Python 依存インストール (uv 推奨)
uv sync            # uv.lock から依存を再現
# または: poetry install

# 3. Playwright ブラウザインストール
uv run playwright install --with-deps chromium
# または: python -m playwright install --with-deps chromium

# 4. 環境変数の設定
cp .env.example .env
# .env を編集して各種認証情報を設定 (後述の「環境変数一覧」参照)

# 5. 動作確認
uv run python -m scripts.ship health
```

## 実行例

```bash
# Shopify 注文番号を指定して発送 (最もよく使うコマンド)
uv run python -m scripts.ship 2098

# Supabase 上の発送対象を一括処理
uv run python -m scripts.ship

# pending rentals の確認のみ (処理なし)
uv run python -m scripts.ship check

# 設定状態の確認
uv run python -m scripts.ship health

# テスト用 JSON ペイロードで実行 (DB 更新なし)
uv run python -m scripts.ship test payload.json
```

## プロジェクト構成

```text
yamato-shipping-bot/
├── scripts/                    # メインコード
│   ├── __main__.py             # エントリーポイントラッパー
│   ├── ship.py                 # CLI コマンド (ship/check/health/test/<注文番号>)
│   ├── yamato_automation.py    # Playwright 自動操作
│   ├── shopify_client.py       # Shopify GraphQL 連携
│   ├── supabase_client.py      # Supabase PostgREST 連携
│   ├── notify.py               # LINE Notify 連携
│   ├── models.py               # Pydantic モデル
│   └── config.py               # 環境設定
├── tests/                      # テスト
├── qr_codes/                   # 生成された QR コードスクリーンショット
├── .env.example                # 環境変数テンプレート
├── pyproject.toml              # 依存管理
├── uv.lock                     # uv ロックファイル
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## 環境変数一覧

`.env.example` をコピーして `.env` に設定してください。

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `KURONEKO_LOGIN_ID` | Yes | クロネコメンバーズ ログイン ID |
| `KURONEKO_PASSWORD` | Yes | クロネコメンバーズ パスワード |
| `SENDER_NAME` | Yes | 依頼主の氏名 (アドレス帳検索用) |
| `SENDER_POSTAL_CODE` | Yes | 依頼主の郵便番号 |
| `SENDER_ADDRESS1` | Yes | 依頼主の住所 |
| `SENDER_ADDRESS2` | - | 依頼主の建物名等 |
| `SENDER_PHONE` | Yes | 依頼主の電話番号 |
| `SHOPIFY_STORE` | Yes* | Shopify ストア名 (*注文番号モードで必須) |
| `SHOPIFY_CLIENT_ID` | Yes* | Shopify Client ID |
| `SHOPIFY_CLIENT_SECRET` | Yes* | Shopify Client Secret |
| `SUPABASE_URL` | Yes** | Supabase Project URL (**バッチモードで必須) |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes** | Supabase service_role key |
| `LINE_NOTIFY_TOKEN` | - | LINE Notify アクセストークン |
| `DEFAULT_PACKAGE_SIZE` | - | デフォルト荷物サイズ (default: `compact`) |
| `PREFERRED_SHIPPING_LOCATION` | - | 希望の発送場所 (例: `セブンイレブン　　神戸本山`) |
| `HEADLESS_BROWSER` | - | Playwright headless モード (default: `true`) |

## 処理フロー

1. Shopify / Supabase から発送対象データを取得
2. Playwright で Chromium を起動し、ヤマト「スマホで送る」にアクセス
3. クロネコメンバーズ SSO で毎回フレッシュログイン
4. フォーム自動入力: お届け先 → 依頼主 → 品名 (固定: スマートフォン) → サイズ (宅急便コンパクト) → 配達日時
5. 下書き保存 → 確認画面スクリーンショット (`qr_codes/`)
6. (バッチモード) Supabase の `rentals.shipping_status` を `shipped` に更新
7. LINE Notify で QR コード画像をスマホに送信
8. コンビニで QR コードを提示して発送

## Docker で実行

```bash
docker compose run --rm runner ship
docker compose run --rm runner check
```

## GitHub Actions (自動実行)

GitHub Secrets に環境変数を設定すれば毎日 10:00 JST に自動実行されます。
手動実行: Actions タブ > "Daily Shipping" > "Run workflow"

## 運用アーキテクチャ

```text
Shopify (注文データ)
  ↓
yamato-shipping-bot (Playwright 自動操作)
  ↓
ヤマト「スマホで送る」下書き保存
  ↓
LINE Notify (QR コード画像をスマホへ送信)
  ↓
コンビニで QR コードを提示して発送
```
