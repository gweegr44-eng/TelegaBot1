"""Отправка, редактирование и удаление сообщений через HTTP API MAX."""
import logging
import aiohttp
from config import MAX_BOT_TOKEN, MAX_BOT_API_URL

logger = logging.getLogger(__name__)


async def _send_request(method: str, url: str, params: dict, body: dict = None):
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
            elif method == "DELETE":
                async with session.delete(url, params=params, headers=headers) as r:
                    return r.status, await r.text()
    except Exception as e:
        logger.error(f"[Notify] HTTP exception: {e}", exc_info=True)
        return None, str(e)


async def _delete_message(message_id: str):
    if not message_id:
        return False
    url = f"{MAX_BOT_API_URL}/messages"
    status, resp = await _send_request("DELETE", url, {"message_id": message_id})
    if status == 200:
        logger.info(f"[Notify] deleted {message_id}")
        return True
    logger.warning(f"[Notify] delete FAIL {status}: {resp[:200]}")
    return False


def _menu_keyboard():
    return {
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


async def notify_report_sent(
    user_id: int,
    is_closing: bool,
    notification_message_id: str = None,
    main_message_id: str = None,
):
    """
    1. Удаляет уведомление о слоте (если есть).
    2. Редактирует главное сообщение (main) на «Отчёт отправлен».
    3. Если main не отредактировался — отправляет новое.
    """
    if is_closing:
        text = "✅ *Отчёт принят. Смена закрыта.*\n\nСпасибо за работу! До завтра 👋"
    else:
        text = "✅ *Отчёт отправлен*\n\nПродолжай в том же духе!"

    body = {
        "text": text,
        "format": "markdown",
        "attachments": [_menu_keyboard()],
    }

    url = f"{MAX_BOT_API_URL}/messages"

    # 1. Удаляем уведомление (сообщение о слоте 13:30)
    if notification_message_id:
        await _delete_message(notification_message_id)

    # 2. Редактируем main
    if main_message_id:
        logger.info(f"[Notify] PUT edit main_id={main_message_id}")
        status, resp = await _send_request(
            "PUT", url, {"message_id": main_message_id}, body
        )
        if status == 200:
            logger.info(f"[Notify] OK (main edited) user={user_id}")
            return
        logger.warning(f"[Notify] main edit FAIL {status}: {resp[:200]} — fallback to new")

    # 3. Fallback — новое сообщение
    logger.info(f"[Notify] POST new user_id={user_id}")
    status, resp = await _send_request("POST", url, {"user_id": user_id}, body)
    if status == 200:
        logger.info(f"[Notify] OK (new) user={user_id}")
    else:
        logger.error(f"[Notify] POST FAIL {status}: {resp[:200]}")