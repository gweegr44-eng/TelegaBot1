import asyncio
import logging
import signal
import aiomax
from config import MAX_BOT_TOKEN
from BotLogic.handlers import setup_handlers
from BotLogic.scheduler import start_scheduler
from Database.database import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    await init_db()
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