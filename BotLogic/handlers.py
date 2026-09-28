import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select

import aiomax
from Database.database import async_session
from Database.models import Store, User, Shift, Report
from config import SUPERADMIN_ID, SLOTS, TIMEZONE, EMPLOYEE_WEBAPP_URL, MAX_BOT_ID

logger = logging.getLogger(__name__)
tz = ZoneInfo(TIMEZONE)


class CustomWebAppButton(aiomax.buttons.Button):
    """Кнопка Mini App: contact_id (ID бота) + web_app (URL)."""
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


def setup_handlers(bot: aiomax.Bot):

    @bot.on_command("start")
    async def cmd_start(ctx: aiomax.CommandContext):
        user_id = str(ctx.sender.user_id)
        first_name = ctx.sender.first_name or "друг"

        async with async_session() as session:
            result = await session.execute(select(User).where(User.max_user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                session.add(User(max_user_id=user_id, role="employee", first_name=first_name))
                await session.commit()

        await ctx.reply(
            f"👋 Привет, {first_name}!\n\n"
            f"Я бот для сбора отчётов с торговых точек.\n\n"
            f"📌 Команды:\n"
            f"/start_shift <код> — начать смену\n"
            f"/end_shift — закрыть смену\n"
            f"/status — статус смены\n"
            f"/help — помощь"
        )

    @bot.on_command("help")
    async def cmd_help(ctx: aiomax.CommandContext):
        await ctx.reply(
            "📖 Помощь\n\n"
            "▫️ /start_shift <код> — начать смену (пример: /start_shift 070519168)\n"
            "▫️ /end_shift — закрыть смену\n"
            "▫️ /status — статус текущей смены\n\n"
            "Отчёты приходят автоматически в 11:30, 13:30, 15:30, 17:30."
        )

    @bot.on_command("start_shift")
    async def cmd_start_shift(ctx: aiomax.CommandContext):
        user_id = str(ctx.sender.user_id)

        async with async_session() as session:
            result = await session.execute(select(User).where(User.max_user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await ctx.reply("Сначала напиши /start.")
                return

            result = await session.execute(
                select(Shift).where(Shift.user_id == user.id, Shift.is_active == True)
            )
            active = result.scalar_one_or_none()
            if active:
                result = await session.execute(select(Store).where(Store.id == active.store_id))
                store = result.scalar_one_or_none()
                await ctx.reply(
                    f"⚠️ У тебя уже есть активная смена.\n"
                    f"📍 {store.store_code} — {store.address}\n\n"
                    f"Сначала закрой: /end_shift"
                )
                return

            if not ctx.args:
                await ctx.reply("Укажи код точки: `/start_shift 070519168`")
                return

            store_code = ctx.args[0]
            result = await session.execute(select(Store).where(Store.store_code == store_code))
            store = result.scalar_one_or_none()
            if not store:
                await ctx.reply(f"❌ Точка `{store_code}` не найдена.")
                return

            now = datetime.now(tz)
            session.add(Shift(
                user_id=user.id,
                store_id=store.id,
                started_at=now,
                is_active=True,
            ))
            await session.commit()

        await ctx.reply(
            f"✅ Смена начата.\n\n"
            f"📍 Точка: {store.store_code} — {store.address}\n"
            f"🕐 Начало: {now.strftime('%H:%M')}\n\n"
            f"Уведомления будут в 11:30, 13:30, 15:30, 17:30.\n"
            f"Закрыть смену — /end_shift"
        )

    @bot.on_command("end_shift")
    async def cmd_end_shift(ctx: aiomax.CommandContext):
        user_id = str(ctx.sender.user_id)

        async with async_session() as session:
            result = await session.execute(select(User).where(User.max_user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await ctx.reply("Сначала напиши /start.")
                return

            result = await session.execute(
                select(Shift).where(Shift.user_id == user.id, Shift.is_active == True)
            )
            shift = result.scalar_one_or_none()
            if not shift:
                await ctx.reply("У тебя нет активной смены.")
                return

            result = await session.execute(select(Store).where(Store.id == shift.store_id))
            store = result.scalar_one_or_none()

        # URL с флагом closing
        closing_url = f"{EMPLOYEE_WEBAPP_URL}?closing=1"

        kb = aiomax.buttons.KeyboardBuilder()
        kb.add(CustomWebAppButton("📝 Заполнить последний отчёт", bot_id=MAX_BOT_ID, url=closing_url))

        await ctx.reply(
            f"📍 Точка: {store.store_code}\n\n"
            f"Хочешь отправить последний отчёт за смену?\n"
            f"Если нет — отправь /skip_closing",
            keyboard=kb,
        )

    @bot.on_command("skip_closing")
    async def cmd_skip_closing(ctx: aiomax.CommandContext):
        user_id = str(ctx.sender.user_id)

        async with async_session() as session:
            result = await session.execute(select(User).where(User.max_user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await ctx.reply("Сначала напиши /start.")
                return

            result = await session.execute(
                select(Shift).where(Shift.user_id == user.id, Shift.is_active == True)
            )
            shift = result.scalar_one_or_none()
            if not shift:
                await ctx.reply("Нет активной смены.")
                return

            now = datetime.now(tz)
            shift.ended_at = now
            shift.is_active = False
            await session.commit()

        await ctx.reply("✅ Смена закрыта. Хорошего отдыха!")

    @bot.on_command("status")
    async def cmd_status(ctx: aiomax.CommandContext):
        user_id = str(ctx.sender.user_id)

        async with async_session() as session:
            result = await session.execute(select(User).where(User.max_user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                await ctx.reply("Сначала напиши /start.")
                return

            result = await session.execute(
                select(Shift).where(Shift.user_id == user.id, Shift.is_active == True)
            )
            shift = result.scalar_one_or_none()
            if not shift:
                await ctx.reply("📴 Активной смены нет.\n\nНачать: /start_shift <код>")
                return

            result = await session.execute(select(Store).where(Store.id == shift.store_id))
            store = result.scalar_one_or_none()

            today = datetime.now(tz).date()
            result = await session.execute(
                select(Report).where(
                    Report.user_id == user.id,
                    Report.report_date == today,
                )
            )
            reports = result.scalars().all()

        await ctx.reply(
            f"🟢 Смена активна\n"
            f"📍 {store.store_code} — {store.address}\n"
            f"🕐 Начало: {shift.started_at.strftime('%H:%M')}\n"
            f"📊 Отчётов сегодня: {len(reports)}"
        )

    @bot.on_command("add_store")
    async def cmd_add_store(ctx: aiomax.CommandContext):
        if str(ctx.sender.user_id) != str(SUPERADMIN_ID):
            await ctx.reply("⛔ Недостаточно прав.")
            return
        if len(ctx.args) < 2:
            await ctx.reply("Используй: `/add_store <код> <адрес>`")
            return
        code = ctx.args[0]
        addr = " ".join(ctx.args[1:])

        async with async_session() as session:
            result = await session.execute(select(Store).where(Store.store_code == code))
            if result.scalar_one_or_none():
                await ctx.reply(f"⚠️ Точка `{code}` уже существует.")
                return
            session.add(Store(store_code=code, address=addr))
            await session.commit()

        await ctx.reply(f"✅ Точка `{code}` добавлена.")

    @bot.on_command("add_manager")
    async def cmd_add_manager(ctx: aiomax.CommandContext):
        user_id = str(ctx.sender.user_id)
        async with async_session() as session:
            result = await session.execute(select(User).where(User.max_user_id == user_id))
            caller = result.scalar_one_or_none()

        is_allowed = (user_id == str(SUPERADMIN_ID)) or (caller and caller.role in ("manager", "superadmin"))
        if not is_allowed:
            await ctx.reply("⛔ Недостаточно прав.")
            return
        if not ctx.args:
            await ctx.reply("Используй: `/add_manager <max_user_id>`")
            return

        target = ctx.args[0]
        async with async_session() as session:
            result = await session.execute(select(User).where(User.max_user_id == target))
            user = result.scalar_one_or_none()
            if not user:
                session.add(User(max_user_id=target, role="manager"))
            else:
                user.role = "manager"
            await session.commit()

        await ctx.reply(f"✅ `{target}` теперь руководитель.")

    @bot.on_command("test_slot")
    async def cmd_test_slot(ctx: aiomax.CommandContext):
        if str(ctx.sender.user_id) != str(SUPERADMIN_ID):
            await ctx.reply("⛔ Недостаточно прав.")
            return
        if not ctx.args:
            await ctx.reply("Используй: `/test_slot 11:30`")
            return
        slot = ctx.args[0]
        if slot not in SLOTS:
            await ctx.reply(f"❌ Доступные слоты: {', '.join(SLOTS)}")
            return
        from BotLogic.scheduler import send_slot_notification
        await send_slot_notification(bot, slot)
        await ctx.reply(f"✅ Уведомления для слота `{slot}` отправлены.")