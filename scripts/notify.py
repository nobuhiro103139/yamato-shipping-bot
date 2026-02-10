import logging
from pathlib import Path

import httpx

from scripts.config import get_settings

logger = logging.getLogger(__name__)

LINE_NOTIFY_API = "https://notify-api.line.me/api/notify"


async def send_line_notify(message: str, image_path: str = "") -> bool:
    settings = get_settings()
    if not settings.line_notify_configured:
        logger.warning("LINE Notify token not configured, skipping notification")
        return False

    headers = {"Authorization": f"Bearer {settings.line_notify_token}"}
    data = {"message": message}

    try:
        async with httpx.AsyncClient() as client:
            if image_path and Path(image_path).exists():
                with open(image_path, "rb") as f:
                    files = {"imageFile": (Path(image_path).name, f, "image/png")}
                    resp = await client.post(
                        LINE_NOTIFY_API,
                        headers=headers,
                        data=data,
                        files=files,
                        timeout=30.0,
                    )
            else:
                resp = await client.post(
                    LINE_NOTIFY_API,
                    headers=headers,
                    data=data,
                    timeout=30.0,
                )

        if resp.status_code == 200:
            logger.info("LINE Notify sent: %s", message[:50])
            return True

        logger.error("LINE Notify failed (%d): %s", resp.status_code, resp.text)
        return False

    except Exception:
        logger.exception("LINE Notify request failed")
        return False


async def notify_shipment_result(
    order_number: str, success: bool, qr_code_path: str = "", error: str = ""
) -> None:
    if success:
        msg = f"\n[発送完了] {order_number}\nQRコード画像を添付します"
        await send_line_notify(msg, image_path=qr_code_path)
    else:
        msg = f"\n[発送失敗] {order_number}\nエラー: {error}"
        await send_line_notify(msg)


async def notify_batch_summary(completed: int, failed: int, total: int) -> None:
    msg = f"\n[発送バッチ完了]\n成功: {completed}/{total}\n失敗: {failed}/{total}"
    await send_line_notify(msg)
