import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

import aiomax
from Database.database import async_session
from Database.models import User, Store, Shift
from BotLogic import messages as msg
from config import SLOTS, TIMEZONE, EMPLOYEE_WEBAPP_URL, MAX_BOT_ID

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
tz = ZoneInfo(TIMEZONE)


class CustomWebAppButton(aiomax.buttons.Button):
    def __init__(self, text, bot_id, url):
        super().__init__("open_app", text)
        self.bot_id = bot_id
        self.url = url

    def to_json(self):
        return {
            "type": "open_app",
            "text": self.text,
            "contact_id": self.bot_id,
            "web_app": self.url,
        }


def start_scheduler(bot: aiomax.Bot):
    for slot in SLOTS:
        h, m = slot.split(":")
        scheduler.add_job(
            send_slot_notification,
            CronTrigger(hour=int(h), minute=int(m), timezone=tz),
            args=[bot, slot],
            id=f"slot_{slot}", replace_existing=True,
        )
    scheduler.add_job(remind_close_shift, CronTrigger(hour=21, minute=0, timezone=tz),
                      args=[bot], id="remind_2100", replace_existing=True)
    scheduler.add_job(warn_auto_close, CronTrigger(hour=23, minute=30, timezone=tz),
                      args=[bot], id="warn_2330", replace_existing=True)
    scheduler.add_job(auto_close_shifts, CronTrigger(hour=23, minute=59, timezone=tz),
                      args=[bot], id="autoclose_2359", replace_existing=True)
    scheduler.start()
    logger.info(f"[Scheduler] Запущен. Слоты: {SLOTS}")


async def _get_active_shifts(session):
    result = await session.execute(select(Shift).where(Shift.is_active == True))
    shifts = result.scalars().all()
    out = []
    for sh in shifts:
        u = (await session.execute(select(User).where(User.id == sh.user_id))).scalar_one_or_none()
        if not u or u.role != "employee":
            continue
        s = (await session.execute(select(Store).where(Store.id == sh.store_id))).scalar_one_or_none()
        if s:
            out.append((u, s, sh))
    return out


async def _remember_temp_message(user_id: int, message_id: str):
    """Сохраняет ID временного сообщения (напоминания)."""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        u = result.scalar_one_or_none()
        if not u:
            return
        existing = []
        if u.temp_messages:
            try:
                existing = json.loads(u.temp_messages)
            except Exception:
                existing = []
        existing.append(str(message_id))
        u.temp_messages = json.dumps(existing)
        await session.commit()


async def send_slot_notification(bot, slot):
    logger.info(f"[Scheduler] Слот {slot}")
    async with async_session() as session:
        entries = await _get_active_shifts(session)
        for user, store, shift in entries:
            url = f"{EMPLOYEE_WEBAPP_URL}?slot={slot}"
            kb = aiomax.buttons.KeyboardBuilder()
            kb.add(CustomWebAppButton("📝 Отчёт", MAX_BOT_ID, url))
            try:
                sent = await bot.send_message(
                    user_id=int(user.max_user_id),
                    text=f"⏰ Отчёт за **{slot}**.\n📍 Точка: {store.store_code}\nНажми кнопку.",
                    format="markdown", keyboard=kb,
                )
                if sent and getattr(sent, "id", None):
                    msg_id = str(sent.id)
                    async with async_session() as sess2:
                        result = await sess2.execute(select(Shift).where(Shift.id == shift.id))
                        sh = result.scalar_one_or_none()
                        if sh:
                            sh.last_message_id = msg_id
                            await sess2.commit()
                    await _remember_temp_message(user.id, msg_id)
            except Exception as e:
                logger.error(f"Ошибка: {e}")


async def remind_close_shift(bot):
    async with async_session() as session:
        for user, store, shift in await _get_active_shifts(session):
            try:
                sent = await bot.send_message(
                    user_id=int(user.max_user_id), text=msg.REMIND_CLOSE
                )
                if sent and getattr(sent, "id", None):
                    await _remember_temp_message(user.id, sent.id)
            except Exception:
                pass


async def warn_auto_close(bot):
    async with async_session() as session:
        for user, store, shift in await _get_active_shifts(session):
            try:
                sent = await bot.send_message(
                    user_id=int(user.max_user_id), text=msg.WARN_AUTO_CLOSE
                )
                if sent and getattr(sent, "id", None):
                    await _remember_temp_message(user.id, sent.id)
            except Exception:
                pass


async def auto_close_shifts(bot):
    now = datetime.now(tz)
    count = 0
    async with async_session() as session:
        for user, store, shift in await _get_active_shifts(session):
            shift.ended_at = now.replace(tzinfo=None)
            shift.is_active = False
            shift.is_auto_closed = True
            shift.pending_closing = False
            count += 1
            try:
                await bot.send_message(user_id=int(user.max_user_id),
                                       text=msg.SHIFT_AUTO_CLOSED)
            except Exception:
                pass
        await session.commit()
    logger.info(f"[Scheduler] Автозакрыто смен: {count}")