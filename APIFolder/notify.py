"""Отправка и редактирование сообщений через HTTP API MAX."""
import logging
import aiohttp
from config import MAX_BOT_TOKEN, MAX_BOT_API_URL

logger = logging.getLogger(__name__)


async def _send_request(method: str, url: str, params: dict, body: dict = None):
    """Универсальный запрос к MAX API."""
    headers = {"Authorization": MAX_BOT_TOKEN}
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if method == "POST":
                async with session.post(url, params=params, json=body, headers=headers) as r:
                    return r.status, await r.text()
            elif method == "PUT":
                async with session.put(url, params=params, json=body, headers=headers) as r:
                    return r.status, await r.text()
    except Exception as e:
        logger.error(f"[Notify] HTTP exception: {e}", exc_info=True)
        return None, str(e)


async def notify_report_sent(user_id: int, is_closing: bool, message_id: str = None):
    """
    Редактирует (если есть message_id) или отправляет новое уведомление.
    """
    if is_closing:
        text = "✅ *Отчёт принят. Смена закрыта.*\n\nСпасибо за работу! До завтра 👋"
    else:
        text = "✅ *Отчёт отправлен*\n\nПродолжай в том же духе!"

    body = {
        "text": text,
        "format": "markdown",
        "attachments": [
            {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [
                        [
                            {
                                "type": "callback",
                                "text": "🏠 В меню",
                                "payload": "back",
                            }
                        ]
                    ]
                }
            }
        ]
    }

    url = f"{MAX_BOT_API_URL}/messages"

    # Попытка редактирования
    if message_id:
        logger.info(f"[Notify] PUT edit message_id={message_id}")
        status, resp = await _send_request(
            "PUT", url, {"message_id": message_id}, body
        )
        if status == 200:
            logger.info(f"[Notify] OK (edited) user={user_id}")
            return
        else:
            logger.warning(f"[Notify] edit FAIL {status}: {resp[:200]} — fallback to new")

    # Новое сообщение
    logger.info(f"[Notify] POST new user_id={user_id}")
    status, resp = await _send_request(
        "POST", url, {"user_id": user_id}, body
    )
    if status == 200:
        logger.info(f"[Notify] OK (new) user={user_id}")
    else:
        logger.error(f"[Notify] POST FAIL {status}: {resp[:200]}")