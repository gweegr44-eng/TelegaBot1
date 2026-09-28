import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

import aiomax
from Database.database import async_session
from Database.models import User, Store, Shift
from config import SLOTS, TIMEZONE, EMPLOYEE_WEBAPP_URL, MAX_BOT_ID

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()
tz = ZoneInfo(TIMEZONE)


class CustomWebAppButton(aiomax.buttons.Button):
    def __init__(self, text: str, bot_id: int, url: str):
        super().__init__("open_app", text)
        self.bot_id = bot_id
        self.url = url

    def to_json(self) -> dict:
        return {
            "type": "open_app",
            "text": self.text,
            "contact_id": self.bot_id,
            "web_app": self.url,
        }


def start_scheduler(bot: aiomax.Bot):
    # 4 фиксированных слота
    for slot in SLOTS:
        hour, minute = slot.split(":")
        scheduler.add_job(
            send_slot_notification,
            CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
            args=[bot, slot],
            id=f"slot_{slot}",
            replace_existing=True,
        )

    # 21:00 — напоминание закрыть смену
    scheduler.add_job(
        remind_close_shift,
        CronTrigger(hour=21, minute=0, timezone=tz),
        args=[bot], id="remind_2100", replace_existing=True,
    )

    # 23:30 — предупреждение
    scheduler.add_job(
        warn_auto_close,
        CronTrigger(hour=23, minute=30, timezone=tz),
        args=[bot], id="warn_2330", replace_existing=True,
    )

    # 23:59 — автозакрытие
    scheduler.add_job(
        auto_close_shifts,
        CronTrigger(hour=23, minute=59, timezone=tz),
        args=[bot], id="autoclose_2359", replace_existing=True,
    )

    scheduler.start()
    logger.info(f"[Scheduler] Запущен. Слоты: {SLOTS}")


async def _get_active_shift_users(session):
    """Возвращает список кортежей (user, store, shift)."""
    result = await session.execute(select(Shift).where(Shift.is_active == True))
    shifts = result.scalars().all()
    out = []
    for sh in shifts:
        result = await session.execute(select(User).where(User.id == sh.user_id))
        user = result.scalar_one_or_none()
        result = await session.execute(select(Store).where(Store.id == sh.store_id))
        store = result.scalar_one_or_none()
        if user and store:
            out.append((user, store, sh))
    return out


async def send_slot_notification(bot: aiomax.Bot, slot: str):
    logger.info(f"[Scheduler] Слот {slot}")
    async with async_session() as session:
        entries = await _get_active_shift_users(session)
        for user, store, shift in entries:
            url = f"{EMPLOYEE_WEBAPP_URL}?slot={slot}"
            kb = aiomax.buttons.KeyboardBuilder()
            kb.add(CustomWebAppButton("📝 Заполнить отчёт", bot_id=MAX_BOT_ID, url=url))
            try:
                await bot.send_message(
                    user_id=int(user.max_user_id),
                    text=(
                        f"⏰ Время отчёта за **{slot}**.\n"
                        f"📍 Точка: {store.store_code}\n"
                        f"Нажми кнопку ниже."
                    ),
                    keyboard=kb,
                )
                logger.info(f"→ {user.max_user_id}")
            except Exception as e:
                logger.error(f"Ошибка {user.max_user_id}: {e}")


async def remind_close_shift(bot: aiomax.Bot):
    async with async_session() as session:
        for user, store, shift in await _get_active_shift_users(session):
            try:
                await bot.send_message(
                    user_id=int(user.max_user_id),
                    text="🕘 Если ты закончил работу — закрой смену: /end_shift",
                )
            except Exception:
                pass


async def warn_auto_close(bot: aiomax.Bot):
    async with async_session() as session:
        for user, store, shift in await _get_active_shift_users(session):
            try:
                await bot.send_message(
                    user_id=int(user.max_user_id),
                    text="⏰ Смена закроется автоматически через 30 минут.",
                )
            except Exception:
                pass


async def auto_close_shifts(bot: aiomax.Bot):
    now = datetime.now(tz)
    count = 0
    async with async_session() as session:
        for user, store, shift in await _get_active_shift_users(session):
            shift.ended_at = now
            shift.is_active = False
            shift.is_auto_closed = True
            count += 1
            try:
                await bot.send_message(
                    user_id=int(user.max_user_id),
                    text="🌙 Смена закрыта автоматически. Хорошего отдыха!",
                )
            except Exception:
                pass
        await session.commit()
    logger.info(f"[Scheduler] Автозакрыто смен: {count}")