import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiomax
from sqlalchemy import select

from config import MAX_BOT_TOKEN, TIMEZONE
from BotLogic.handlers import setup_handlers
from BotLogic.scheduler import start_scheduler
from Database.database import init_db, async_session
from Database.models import Shift

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def close_stale_shifts():
    """Закрывает смены, которые висят больше 24 часов."""
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz).replace(tzinfo=None)
    threshold = now - timedelta(hours=24)

    async with async_session() as session:
        result = await session.execute(
            select(Shift).where(Shift.is_active == True, Shift.started_at < threshold)
        )
        stale = result.scalars().all()
        for sh in stale:
            sh.is_active = False
            sh.ended_at = now
            sh.is_auto_closed = True
            sh.pending_closing = False
        await session.commit()

        if stale:
            logger.info(f"[Bot] Закрыто зависших смен: {len(stale)}")


async def main():
    await init_db()
    await close_stale_shifts()

    bot = aiomax.Bot(MAX_BOT_TOKEN, use_certificate=True, default_format="markdown")
    setup_handlers(bot)
    start_scheduler(bot)
    logger.info("[Bot] Бот запущен...")

    while True:
        try:
            await bot.start_polling()
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("[Bot] Остановка...")
            break
        except Exception as e:
            logger.error(f"[Bot] Ошибка polling: {e}. Переподключение через 10 сек...")
            try:
                await asyncio.sleep(10)
            except (KeyboardInterrupt, asyncio.CancelledError):
                logger.info("[Bot] Остановка...")
                break


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Bot] Остановлен.")