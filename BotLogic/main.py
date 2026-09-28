import asyncio
import logging
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
        except Exception as e:
            logger.error(f"[Bot] Ошибка polling: {e}. Переподключение через 10 сек...")
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())