"""B2 クラウド (ヤマト) 取込用 CSV を生成するモジュール.

仕様:
- 文字コード: Shift_JIS (CP932)
- 改行: CRLF
- 区切り: カンマ
- 全フィールド ``"..."`` で引用 (csv.QUOTE_ALL)
- 95 列固定 + ヘッダー行
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.config import Settings
from scripts.models import DeliveryTimeSlot, RentalOrder

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 95 列のヘッダー (B2 クラウド取込フォーマット)
HEADER: tuple[str, ...] = (
    "お客様管理番号", "送り状種類", "クール区分", "伝票番号", "出荷予定日",
    "お届け予定日", "配達時間帯", "お届け先コード", "お届け先電話番号",
    "お届け先電話番号枝番", "お届け先郵便番号", "お届け先住所",
    "お届け先アパートマンション名", "お届け先会社・部門１", "お届け先会社・部門２",
    "お届け先名", "お届け先名(ｶﾅ)", "敬称", "ご依頼主コード", "ご依頼主電話番号",
    "ご依頼主電話番号枝番", "ご依頼主郵便番号", "ご依頼主住所",
    "ご依頼主アパートマンション", "ご依頼主名", "ご依頼主名(ｶﾅ)",
    "品名コード１", "品名１", "品名コード２", "品名２", "荷扱い１", "荷扱い２",
    "記事", "ｺﾚｸﾄ代金引換額（税込)", "内消費税額等", "止置き", "営業所コード",
    "発行枚数", "個数口表示フラグ", "請求先顧客コード", "請求先分類コード",
    "運賃管理番号", "クロネコwebコレクトデータ登録",
    "クロネコwebコレクト加盟店番号", "クロネコwebコレクト申込受付番号１",
    "クロネコwebコレクト申込受付番号２", "クロネコwebコレクト申込受付番号３",
    "お届け予定ｅメール利用区分", "お届け予定ｅメールe-mailアドレス", "入力機種",
    "お届け予定ｅメールメッセージ", "お届け完了ｅメール利用区分",
    "お届け完了ｅメールe-mailアドレス", "お届け完了ｅメールメッセージ",
    "クロネコ収納代行利用区分", "予備", "収納代行請求金額(税込)",
    "収納代行内消費税額等", "収納代行請求先郵便番号", "収納代行請求先住所",
    "収納代行請求先住所（アパートマンション名）", "収納代行請求先会社・部門名１",
    "収納代行請求先会社・部門名２", "収納代行請求先名(漢字)",
    "収納代行請求先名(カナ)", "収納代行問合せ先名(漢字)", "収納代行問合せ先郵便番号",
    "収納代行問合せ先住所", "収納代行問合せ先住所（アパートマンション名）",
    "収納代行問合せ先電話番号", "収納代行管理番号", "収納代行品名",
    "収納代行備考", "複数口くくりキー", "検索キータイトル1", "検索キー1",
    "検索キータイトル2", "検索キー2", "検索キータイトル3", "検索キー3",
    "検索キータイトル4", "検索キー4", "検索キータイトル5", "検索キー5",
    "予備", "予備", "投函予定メール利用区分", "投函予定メールe-mailアドレス",
    "投函予定メールメッセージ", "投函完了メール（お届け先宛）利用区分",
    "投函完了メール（お届け先宛）e-mailアドレス",
    "投函完了メール（お届け先宛）メールメッセージ",
    "投函完了メール（ご依頼主宛）利用区分",
    "投函完了メール（ご依頼主宛）e-mailアドレス",
    "投函完了メール（ご依頼主宛）メールメッセージ",
)

assert len(HEADER) == 95, f"HEADER must have 95 columns, got {len(HEADER)}"

# 固定値
INVOICE_TYPE_HASSO = "0"  # 送り状種類: 発払い
ITEM_NAME = "スマートフォン"
HANDLING_NOTE = "精密機械"

# DeliveryTimeSlot → B2 クラウド配達時間帯コード (4桁: 開始HH+終了HH)
TIME_SLOT_TO_B2: dict[DeliveryTimeSlot, str] = {
    DeliveryTimeSlot.NONE: "",
    DeliveryTimeSlot.MORNING: "0812",
    DeliveryTimeSlot.PM_14_16: "1416",
    DeliveryTimeSlot.PM_16_18: "1618",
    DeliveryTimeSlot.PM_18_20: "1820",
    DeliveryTimeSlot.PM_19_21: "1921",
}

ENCODING = "cp932"
NEWLINE = "\r\n"


def _format_postal_code(raw: str) -> str:
    """郵便番号を ``XXX-XXXX`` 形式に整形."""
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    return raw or ""


def _format_phone(raw: str) -> str:
    """電話番号をB2向け国内形式に整形.

    - `+81xxxxxxxxxx` は先頭を `0` に戻す
    - 既にハイフン付きでも、まず数字へ正規化してから整形する
    - 11桁は `XXX-XXXX-XXXX`
    - 10桁は `03/06` のみ `XX-XXXX-XXXX`、それ以外は `XXX-XXX-XXXX`
    """
    if not raw:
        return ""

    digits = "".join(ch for ch in raw if ch.isdigit())

    # 日本の国番号 +81 を国内表記 0 始まりへ戻す
    if digits.startswith("81") and len(digits) in (11, 12):
        digits = f"0{digits[2:]}"

    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if len(digits) == 10:
        if digits.startswith(("03", "06")):
            return f"{digits[:2]}-{digits[2:6]}-{digits[6:]}"
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return digits or raw


def _format_delivery_date(yyyymmdd: str) -> str:
    """``YYYYMMDD`` → ``YYYY/MM/DD`` 変換. 不正値は空文字を返す."""
    if not yyyymmdd or len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return ""
    return f"{yyyymmdd[:4]}/{yyyymmdd[4:6]}/{yyyymmdd[6:]}"


def _today_jst() -> str:
    """当日の JST 日付を ``YYYY/MM/DD`` 形式で返す (出荷予定日用)."""
    return datetime.now(JST).strftime("%Y/%m/%d")


PREFECTURE_NORMALIZATION: dict[str, str] = {
    "hokkaido": "北海道",
    "aomori": "青森県",
    "iwate": "岩手県",
    "miyagi": "宮城県",
    "akita": "秋田県",
    "yamagata": "山形県",
    "fukushima": "福島県",
    "ibaraki": "茨城県",
    "tochigi": "栃木県",
    "gunma": "群馬県",
    "saitama": "埼玉県",
    "chiba": "千葉県",
    "tokyo": "東京都",
    "kanagawa": "神奈川県",
    "niigata": "新潟県",
    "toyama": "富山県",
    "ishikawa": "石川県",
    "fukui": "福井県",
    "yamanashi": "山梨県",
    "nagano": "長野県",
    "gifu": "岐阜県",
    "shizuoka": "静岡県",
    "aichi": "愛知県",
    "mie": "三重県",
    "shiga": "滋賀県",
    "kyoto": "京都府",
    "osaka": "大阪府",
    "hyogo": "兵庫県",
    "nara": "奈良県",
    "wakayama": "和歌山県",
    "tottori": "鳥取県",
    "shimane": "島根県",
    "okayama": "岡山県",
    "hiroshima": "広島県",
    "yamaguchi": "山口県",
    "tokushima": "徳島県",
    "kagawa": "香川県",
    "ehime": "愛媛県",
    "kochi": "高知県",
    "fukuoka": "福岡県",
    "saga": "佐賀県",
    "nagasaki": "長崎県",
    "kumamoto": "熊本県",
    "oita": "大分県",
    "miyazaki": "宮崎県",
    "kagoshima": "鹿児島県",
    "okinawa": "沖縄県",
}


def _normalize_prefecture(raw: str) -> str:
    """Shopify由来の都道府県表記を B2 向け日本語表記へ寄せる."""
    if not raw:
        return ""
    normalized = (
        raw.strip()
        .lower()
        .replace("ō", "o")
        .replace("ô", "o")
        .replace("ū", "u")
        .replace("â", "a")
        .replace("î", "i")
        .replace("ê", "e")
    )
    return PREFECTURE_NORMALIZATION.get(normalized, raw)


def _join_address(order: RentalOrder) -> str:
    """都道府県+市区町村+address1 を結合してお届け先住所文字列を生成."""
    addr = order.shipping_address
    parts = [_normalize_prefecture(addr.province), addr.city, addr.address1]
    return "".join(p for p in parts if p)


def _recipient_name(order: RentalOrder) -> str:
    """お届け先名 (姓 + 半角空白 + 名)."""
    addr = order.shipping_address
    if addr.last_name and addr.first_name:
        return f"{addr.last_name} {addr.first_name}"
    return addr.last_name or addr.first_name or ""


def _building(order: RentalOrder) -> str:
    """アパマン名 (address2 優先, 無ければ building)."""
    addr = order.shipping_address
    return addr.address2 or addr.building or ""


def build_b2_row(order: RentalOrder, settings: Settings) -> list[str]:
    """注文 1 件を 95 列の B2 取込行に変換."""
    row = [""] * 95

    # お客様管理番号 (列1): 注文番号を安定した照合キーとして使用
    row[0] = order.order_number
    # 送り状種類 (列2): 発払い
    row[1] = INVOICE_TYPE_HASSO
    # 出荷予定日 (列5): 当日
    row[4] = _today_jst()
    # お届け予定日 (列6): order.delivery_date (YYYYMMDD → YYYY/MM/DD)
    row[5] = _format_delivery_date(order.delivery_date)
    # 配達時間帯 (列7)
    row[6] = TIME_SLOT_TO_B2.get(order.delivery_time, "")
    # お届け先電話番号 (列9)
    row[8] = _format_phone(order.shipping_address.phone)
    # お届け先郵便番号 (列11)
    row[10] = _format_postal_code(order.shipping_address.postal_code)
    # お届け先住所 (列12)
    row[11] = _join_address(order)
    # お届け先アパートマンション名 (列13)
    row[12] = _building(order)
    # お届け先名 (列16)
    row[15] = _recipient_name(order)

    # ご依頼主電話番号 (列20)
    row[19] = _format_phone(settings.sender_phone)
    # ご依頼主郵便番号 (列22)
    row[21] = _format_postal_code(settings.sender_postal_code)
    # ご依頼主住所 (列23): SENDER_ADDRESS1 + SENDER_ADDRESS2
    sender_addr = settings.sender_address1
    if settings.sender_address2:
        sender_addr = f"{sender_addr}{settings.sender_address2}"
    row[22] = sender_addr
    # ご依頼主名 (列25)
    row[24] = settings.sender_name

    # 品名１ (列28)
    row[27] = ITEM_NAME
    # 荷扱い１ (列31)
    row[30] = HANDLING_NOTE

    # 請求先顧客コード (列40)
    row[39] = settings.b2_billing_customer_code
    # 運賃管理番号 (列42)
    row[41] = settings.b2_freight_management_number

    return row


def daily_output_path(output_dir: str | Path, when: datetime | None = None) -> Path:
    """``b2_output/b2cloud_YYYYMMDD.csv`` のパスを返す."""
    when = when or datetime.now(JST)
    return Path(output_dir) / f"b2cloud_{when.strftime('%Y%m%d')}.csv"


def _read_existing_order_keys(path: Path) -> set[str]:
    """既存 CSV からお客様管理番号 (列0) のセットを返す (ヘッダー行は除外)."""
    try:
        raw = path.read_bytes()
        text = raw.decode(ENCODING)
    except OSError:
        return set()
    keys: set[str] = set()
    for row in csv.reader(text.splitlines()):
        if row and row[0] and row[0] != HEADER[0]:
            keys.add(row[0])
    return keys


def append_b2_csv(orders: list[RentalOrder], settings: Settings) -> Path:
    """注文を当日の B2 CSV ファイルに追記 (無ければヘッダー付きで新規作成).

    重複防止: 既存 CSV の「お客様管理番号」列を読み取り、同じ注文番号がすでに
    存在する場合はスキップする。

    CP932 変換失敗: ``errors="replace"`` は使わない。変換できない文字があれば
    どの注文・列が原因かを示す ``ValueError`` を送出する。

    Returns:
        出力先ファイルパス
    """
    if not orders:
        raise ValueError("orders is empty")

    output_path = daily_output_path(settings.b2_output_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not output_path.exists()

    # 重複排除: 既存 CSV に含まれる注文番号をスキップ
    if not is_new:
        existing_keys = _read_existing_order_keys(output_path)
        unique_orders: list[RentalOrder] = []
        for order in orders:
            if order.order_number in existing_keys:
                logger.warning(
                    "Skipping duplicate order %s — already present in %s",
                    order.order_number,
                    output_path,
                )
            else:
                unique_orders.append(order)
        if not unique_orders:
            logger.info(
                "All %d order(s) already present in %s — nothing to write",
                len(orders),
                output_path,
            )
            return output_path
        orders = unique_orders

    rows = [build_b2_row(o, settings) for o in orders]

    # CP932 エンコード検証 — サイレント文字化けを禁止し、原因を特定
    for order, row in zip(orders, rows):
        for col_idx, field in enumerate(row):
            try:
                field.encode(ENCODING)
            except UnicodeEncodeError as exc:
                raise ValueError(
                    f"CP932エンコード失敗: 注文={order.order_number!r}, "
                    f"列{col_idx + 1} ({HEADER[col_idx]})={field!r}"
                ) from exc

    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator=NEWLINE)
    if is_new:
        writer.writerow(HEADER)
    for row in rows:
        writer.writerow(row)

    data = buf.getvalue().encode(ENCODING)
    mode = "wb" if is_new else "ab"
    with open(output_path, mode) as f:
        f.write(data)

    logger.info(
        "B2 CSV %s: %s (%d row(s))",
        "created" if is_new else "appended",
        output_path,
        len(rows),
    )
    return output_path
