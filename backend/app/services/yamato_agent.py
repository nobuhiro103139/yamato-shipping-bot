import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import Settings, get_settings
from app.models.order import Shipment, ShippingResult, ShippingStatus

if TYPE_CHECKING:
    from browser_use import Agent

logger = logging.getLogger(__name__)

YAMATO_SEND_URL = "https://sp-send.kuronekoyamato.co.jp/"
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

IPHONE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6 Mobile/15E148 Safari/604.1"
)


def _build_task_prompt(shipment: Shipment, settings: Settings) -> str:
    """Build a detailed natural-language task prompt for the Browser Use agent."""
    last_name = shipment.recipient_last_name
    first_name = shipment.recipient_first_name
    postal_code = shipment.recipient_postal_code.replace("-", "")
    phone = (
        shipment.recipient_phone
        .replace("+81 ", "0")
        .replace("+81", "0")
        .replace("-", "")
    )
    product_name = shipment.product_name or "スマートフォン"
    size_label = shipment.package_size_label

    lines = [
        f"ヤマト運輸「スマホで送る」({YAMATO_SEND_URL}) で荷物の送り状を作成してください。",
        "",
        "## ログイン",
        "保存済みのセッション（auth.json）でログイン状態が維持されています。",
        "もしログイン画面にリダイレクトされた場合は、処理を中止してください。",
        "",
        "## 荷物の新規作成",
        "ログイン後、荷物一覧ページが表示されたら「荷物を送る」タブを選択して新規作成を開始してください。",
        "1. 「通常の荷物を送る」をクリック",
        "2. 「発払い」を選択",
        "3. 「１個」を選択",
        "",
        "## 荷物情報の設定",
        f"4. サイズは「{size_label}」を選択",
        f"5. 品名に「{product_name}」と入力",
        "6. 「精密機械」の取り扱い注意チェックボックスをONにする",
        "7. 「禁制品に該当しません」のチェックボックスをONにする",
        "8. 「次へ」ボタンをクリック",
        "",
        "## お届け先情報",
        "9. 「直接住所を入力する」を選択",
        f"10. 姓: 「{last_name}」",
        f"11. 名: 「{first_name}」",
        f"12. 郵便番号: 「{postal_code}」を入力して検索ボタンをクリック",
    ]

    if shipment.recipient_chome:
        lines.append(f"13. 丁目の選択肢が表示されたら「{shipment.recipient_chome}丁目」を選択")

    if shipment.recipient_banchi:
        lines.append(f"14. 番地に「{shipment.recipient_banchi}」を入力")

    if shipment.recipient_go:
        lines.append(f"15. 号に「{shipment.recipient_go}」を入力")

    if shipment.recipient_building:
        lines.append(f"16. 建物名・部屋番号に「{shipment.recipient_building}」を入力")

    lines.extend([
        f"17. 電話番号に「{phone}」を入力",
        "",
    ])

    if shipment.recipient_email:
        lines.extend([
            "## お届け予定通知",
            "18. 「お届け予定をお知らせ」のチェックボックスをONにする",
            f"19. メールアドレスに「{shipment.recipient_email}」を入力",
            "",
        ])

    lines.extend([
        "## アドレス帳登録",
        "20. 「アドレス帳へ登録」のチェックボックスがONの場合はOFFにする",
        "",
        "21. 「次へ」ボタンをクリック",
        "",
        "## ご依頼主情報",
        "22. 「アドレス帳から選択」をクリック",
    ])

    sender_name = settings.sender_name or "フツテック"
    lines.extend([
        f"23. アドレス帳一覧から「{sender_name}」を含む依頼主を選択",
        "24. 依頼主情報の確認ページで「次へ」をクリック",
        "",
        "## 発送場所・配達日時",
        "25. 発送場所は「お届け先住所の近くから発送」を選択",
    ])

    if shipment.shipping_date:
        lines.append(f"26. 発送予定日を「{shipment.shipping_date}」に設定")

    if shipment.delivery_date:
        lines.append(f"27. お届け日を「{shipment.delivery_date}」に設定")

    if shipment.delivery_time:
        lines.append(f"28. お届け時間帯を「{shipment.delivery_time}」に設定")

    lines.extend([
        "29. 「次へ」をクリック",
        "",
        "## 下書き保存",
        "30. 確認ページで「保存して別の荷物を送る」ボタンをクリックして下書き保存する",
        "31. ダイアログが表示されたら「OK」をクリック",
        "",
        "## 完了確認",
        f"荷物一覧に戻ったら、「{last_name} {first_name}」の送り状が「送り状作成中」として表示されていることを確認してください。",
    ])

    return "\n".join(lines)


def _build_browser_config() -> "Browser":
    """Build Browser Use Browser configuration with iPhone mobile emulation."""
    from browser_use import Browser

    settings = get_settings()
    auth_path = settings.auth_state_path

    if not Path(auth_path).exists():
        raise FileNotFoundError(
            f"Auth state file not found: {auth_path}. "
            "Run save_auth_state() first to login manually."
        )

    browser_kwargs: dict = {
        "headless": settings.headless_browser,
        "user_agent": IPHONE_USER_AGENT,
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 3,
        "wait_between_actions": 1.0,
        "minimum_wait_page_load_time": 0.5,
        "wait_for_network_idle_page_load_time": 1.0,
        "allowed_domains": [
            "*.kuronekoyamato.co.jp",
            "*.kms.kuronekoyamato.co.jp",
        ],
        "storage_state": auth_path,
    }

    return Browser(**browser_kwargs)


def _get_llm():
    """Initialize the LLM for Browser Use agent."""
    settings = get_settings()
    provider = settings.llm_provider.lower()

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
        )
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
        )
    else:
        raise ValueError(
            f"Unsupported LLM provider: {provider}. Use 'openai' or 'anthropic'."
        )


async def process_shipment(shipment: Shipment) -> ShippingResult:
    """Process a single shipment using Browser Use AI agent.

    The agent navigates Yamato's 'Send via Smartphone' web interface,
    fills in forms based on the shipment data, and saves as draft.
    """
    settings = get_settings()
    identifier = shipment.identifier

    if not settings.llm_api_key:
        return ShippingResult(
            order_id=identifier,
            order_number=identifier,
            status=ShippingStatus.FAILED,
            error_message="LLM API key not configured. Set LLM_API_KEY in .env",
        )

    browser = None
    try:
        from browser_use import Agent

        llm = _get_llm()
        browser = _build_browser_config()
        task = _build_task_prompt(shipment, settings)

        agent = Agent(
            task=task,
            llm=llm,
            browser=browser,
            max_actions_per_step=5,
        )

        logger.info("Processing shipment for %s***", identifier[:2])
        result = await agent.run(max_steps=80)

        screenshot_path = ""
        if result and result.screenshots():
            last_screenshot = result.screenshots()[-1]
            screenshot_file = RESULTS_DIR / f"{identifier}_done.png"
            screenshot_file.write_bytes(last_screenshot)
            screenshot_path = str(screenshot_file)

        if result and result.is_done() and not result.has_errors():
            return ShippingResult(
                order_id=identifier,
                order_number=identifier,
                status=ShippingStatus.COMPLETED,
                qr_code_path=screenshot_path,
            )

        error_msg = "Agent did not complete successfully"
        if result and result.errors():
            error_msg = "; ".join(str(e) for e in result.errors())
        return ShippingResult(
            order_id=identifier,
            order_number=identifier,
            status=ShippingStatus.FAILED,
            qr_code_path=screenshot_path,
            error_message=error_msg,
        )

    except ImportError:
        return ShippingResult(
            order_id=identifier,
            order_number=identifier,
            status=ShippingStatus.FAILED,
            error_message="browser-use is not installed. Run: pip install browser-use langchain-openai",
        )
    except Exception as e:
        logger.exception("Shipment failed for %s", identifier[:2])
        return ShippingResult(
            order_id=identifier,
            order_number=identifier,
            status=ShippingStatus.FAILED,
            error_message=str(e),
        )
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                logger.debug("Browser close failed", exc_info=True)


def load_shipments(path: str = "shipments.json") -> list[Shipment]:
    """Load shipment data from a JSON file."""
    file_path = Path(path)
    if not file_path.exists():
        logger.warning("Shipments file not found: %s", path)
        return []

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Invalid JSON in shipments file %s: %s", path, exc)
        return []

    if isinstance(data, dict):
        data = [data]

    return [Shipment.model_validate(item) for item in data]
