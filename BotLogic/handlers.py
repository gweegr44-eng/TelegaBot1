import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select

import aiomax
from Database.database import async_session
from Database.models import Store, User, Shift, Report
from BotLogic import messages as msg
from config import SLOTS, TIMEZONE, SUPERADMIN_ID

logger = logging.getLogger(__name__)
tz = ZoneInfo(TIMEZONE)

pending_input = {}


def get_next_slot(now):
    now_min = now.hour * 60 + now.minute
    for slot in SLOTS:
        h, m = map(int, slot.split(":"))
        if h * 60 + m > now_min:
            return slot
    return None


def build_main_keyboard(has_shift: bool = False, in_status: bool = False):
    kb = aiomax.buttons.KeyboardBuilder()
    if has_shift:
        if not in_status:
            kb.add(aiomax.buttons.CallbackButton("📊 Статус", payload="status"))
        kb.add(aiomax.buttons.CallbackButton("🔴 Закрыть", payload="close_shift"))
    else:
        kb.add(aiomax.buttons.CallbackButton("🟢 Смена", payload="start_shift"))

    if in_status:
        kb.add(aiomax.buttons.CallbackButton("ℹ️ Инфо", payload="info_status"))
    else:
        kb.add(aiomax.buttons.CallbackButton("ℹ️ Инфо", payload="info"))
    return kb


async def get_user(session, max_user_id: str):
    result = await session.execute(select(User).where(User.max_user_id == max_user_id))
    return result.scalar_one_or_none()


async def get_active_shift(session, user_id: int):
    result = await session.execute(
        select(Shift).where(Shift.user_id == user_id, Shift.is_active == True)
    )
    return result.scalar_one_or_none()


def format_duration(start, end):
    if start.tzinfo is None:
        start = start.replace(tzinfo=tz)
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz)
    delta = end - start
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    return f"{hours} ч {minutes} мин"


def setup_handlers(bot: aiomax.Bot):

    async def _show_main_menu(message, user_id_str: str):
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            if not user:
                user = User(max_user_id=user_id_str, role="employee")
                session.add(user)
                await session.commit()
                await session.refresh(user)
            shift = await get_active_shift(session, user.id)
            store = None
            if shift:
                result = await session.execute(select(Store).where(Store.id == shift.store_id))
                store = result.scalar_one_or_none()

        name = user.first_name or "друг"
        if shift and store:
            text = msg.GREETING_WITH_SHIFT.format(
                name=name, store_code=store.store_code,
                address=store.address,
                started_at=shift.started_at.strftime("%H:%M"),
            )
        else:
            text = msg.GREETING.format(name=name)

        kb = build_main_keyboard(has_shift=shift is not None)

        if message is None:
            await bot.send_message(user_id=int(user_id_str), text=text,
                                   format="markdown", keyboard=kb)
        else:
            try:
                await message.edit(text=text, format="markdown", keyboard=kb)
            except Exception:
                await bot.send_message(user_id=int(user_id_str), text=text,
                                       format="markdown", keyboard=kb)

    async def _show_status(user_id_int: int, edit_msg=None):
        user_id_str = str(user_id_int)
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            shift = await get_active_shift(session, user.id) if user else None

            if not shift:
                text = msg.STATUS_NO_SHIFT
                kb = build_main_keyboard(has_shift=False)
            else:
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
                text = msg.STATUS_ACTIVE.format(
                    store_code=store.store_code,
                    address=store.address,
                    started_at=shift.started_at.strftime("%H:%M"),
                    reports_count=len(reports),
                )
                kb = build_main_keyboard(has_shift=True, in_status=True)

        if edit_msg:
            try:
                await edit_msg.edit(text=text, format="markdown", keyboard=kb)
                return
            except Exception:
                pass
        await bot.send_message(user_id=user_id_int, text=text, format="markdown", keyboard=kb)

    async def _create_shift(user_id_int: int, store_code: str, edit_msg=None):
        user_id_str = str(user_id_int)
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            if not user:
                return
            result = await session.execute(select(Store).where(Store.store_code == store_code))
            store = result.scalar_one_or_none()
            if not store:
                kb = aiomax.buttons.KeyboardBuilder()
                kb.add(aiomax.buttons.CallbackButton("⬅️ Назад", payload="back_to_start_shift"))
                text = msg.STORE_NOT_FOUND.format(code=store_code)
                if edit_msg:
                    try:
                        await edit_msg.edit(text=text, keyboard=kb)
                    except Exception:
                        await bot.send_message(user_id=user_id_int, text=text, keyboard=kb)
                else:
                    await bot.send_message(user_id=user_id_int, text=text, keyboard=kb)
                pending_input[user_id_str] = "store_code"
                return

            now = datetime.now(tz)
            session.add(Shift(
                user_id=user.id, store_id=store.id,
                started_at=now.replace(tzinfo=None),
                is_active=True,
            ))
            user.last_store_id = store.id
            await session.commit()

        next_slot = get_next_slot(now)
        if next_slot:
            text = msg.SHIFT_STARTED.format(
                store_code=store.store_code, address=store.address,
                started_at=now.strftime("%H:%M"),
                next_info=f"⏰ Ближайшее уведомление: {next_slot}",
            )
        else:
            text = msg.SHIFT_STARTED_NO_SLOTS.format(
                store_code=store.store_code, address=store.address,
                started_at=now.strftime("%H:%M"),
            )

        kb = build_main_keyboard(has_shift=True)
        if edit_msg:
            try:
                await edit_msg.edit(text=text, format="markdown", keyboard=kb)
                return
            except Exception:
                pass
        await bot.send_message(user_id=user_id_int, text=text, format="markdown", keyboard=kb)

    async def _handle_start_shift(user_id_int: int, edit_msg=None):
        user_id_str = str(user_id_int)
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            if not user:
                user = User(max_user_id=user_id_str, role="employee")
                session.add(user)
                await session.commit()
                await session.refresh(user)

            shift = await get_active_shift(session, user.id)
            if shift:
                result = await session.execute(select(Store).where(Store.id == shift.store_id))
                store = result.scalar_one_or_none()
                text = msg.SHIFT_ALREADY_ACTIVE.format(
                    store_code=store.store_code, address=store.address,
                    started_at=shift.started_at.strftime("%H:%M"),
                )
                kb = build_main_keyboard(has_shift=True)
                if edit_msg:
                    try:
                        await edit_msg.edit(text=text, format="markdown", keyboard=kb)
                        return
                    except Exception:
                        pass
                await bot.send_message(user_id=user_id_int, text=text, format="markdown", keyboard=kb)
                return

            last_store = None
            if user.last_store_id:
                result = await session.execute(select(Store).where(Store.id == user.last_store_id))
                last_store = result.scalar_one_or_none()

        if last_store:
            text = msg.SAME_STORE_QUESTION.format(
                store_code=last_store.store_code, address=last_store.address,
            )
            kb = aiomax.buttons.KeyboardBuilder()
            kb.add(aiomax.buttons.CallbackButton("✅ Та же", payload="same_store"))
            kb.add(aiomax.buttons.CallbackButton("🔄 Новая", payload="new_store"))
            kb.add(aiomax.buttons.CallbackButton("⬅️ Отмена", payload="back"))
        else:
            pending_input[user_id_str] = "store_code"
            text = msg.ASK_STORE_CODE_FIRST
            kb = aiomax.buttons.KeyboardBuilder()
            kb.add(aiomax.buttons.CallbackButton("⬅️ Отмена", payload="back"))

        if edit_msg:
            try:
                await edit_msg.edit(text=text, format="markdown", keyboard=kb)
                return
            except Exception:
                pass
        await bot.send_message(user_id=user_id_int, text=text, format="markdown", keyboard=kb)

    async def _handle_close_shift(user_id_int: int, edit_msg=None):
        user_id_str = str(user_id_int)
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            if not user:
                return
            shift = await get_active_shift(session, user.id)
            if not shift:
                return
            result = await session.execute(select(Store).where(Store.id == shift.store_id))
            store = result.scalar_one_or_none()

            shift.pending_closing = True
            await session.commit()
            shift_id = shift.id

        from config import EMPLOYEE_WEBAPP_URL, MAX_BOT_ID

        class CustomWebAppButton(aiomax.buttons.Button):
            def __init__(self, text, bot_id, url):
                super().__init__("open_app", text)
                self.bot_id = bot_id
                self.url = url
            def to_json(self):
                return {
                    "type": "open_app", "text": self.text,
                    "contact_id": self.bot_id, "web_app": self.url,
                }

        kb = aiomax.buttons.KeyboardBuilder()
        kb.add(CustomWebAppButton("📝 Отчёт", bot_id=MAX_BOT_ID, url=EMPLOYEE_WEBAPP_URL))
        kb.add(aiomax.buttons.CallbackButton("⏭ Пропустить", payload="skip_closing"))

        text = msg.CLOSING_ASK.format(store_code=store.store_code, address=store.address)

        # Сохраняем ID сообщения ДО редактирования (это тот же message_id)
        result_msg_id = None
        if edit_msg and getattr(edit_msg, "id", None):
            result_msg_id = str(edit_msg.id)

        # Пробуем отредактировать исходное сообщение
        edit_ok = False
        if edit_msg:
            try:
                await edit_msg.edit(text=text, format="markdown", keyboard=kb)
                edit_ok = True
            except Exception:
                pass

        # Если не удалось — отправляем новое
        if not edit_ok:
            sent = await bot.send_message(
                user_id=user_id_int, text=text, format="markdown", keyboard=kb
            )
            if sent and getattr(sent, "id", None):
                result_msg_id = str(sent.id)

        # Сохраняем message_id в БД
        if result_msg_id:
            async with async_session() as session:
                result = await session.execute(select(Shift).where(Shift.id == shift_id))
                sh = result.scalar_one_or_none()
                if sh:
                    sh.last_message_id = result_msg_id
                    await session.commit()
            logger.info(f"[Handler] saved last_message_id={result_msg_id} for shift={shift_id}")

    async def _close_shift_without_report(user_id_int: int, edit_msg=None):
        user_id_str = str(user_id_int)
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            if not user:
                return
            shift = await get_active_shift(session, user.id)
            if not shift:
                text = msg.STATUS_NO_SHIFT
                kb = build_main_keyboard(has_shift=False)
                if edit_msg:
                    try:
                        await edit_msg.edit(text=text, format="markdown", keyboard=kb)
                        return
                    except Exception:
                        pass
                await bot.send_message(user_id=user_id_int, text=text, format="markdown", keyboard=kb)
                return

            result = await session.execute(select(Store).where(Store.id == shift.store_id))
            store = result.scalar_one_or_none()

            now = datetime.now(tz)
            duration = format_duration(shift.started_at, now)
            shift.ended_at = now.replace(tzinfo=None)
            shift.is_active = False
            shift.pending_closing = False
            shift.last_message_id = None
            await session.commit()

        text = msg.SHIFT_CLOSED.format(store_code=store.store_code, duration=duration)
        kb = build_main_keyboard(has_shift=False)

        if edit_msg:
            try:
                await edit_msg.edit(text=text, format="markdown", keyboard=kb)
                return
            except Exception:
                pass
        await bot.send_message(user_id=user_id_int, text=text, format="markdown", keyboard=kb)

    # ========== START ==========
    @bot.on_bot_start()
    async def on_start(ctx: aiomax.CommandContext):
        await _show_main_menu(None, str(ctx.user_id))

    @bot.on_command("start")
    async def cmd_start(ctx: aiomax.CommandContext):
        await _show_main_menu(None, str(ctx.user_id))

    @bot.on_command("help")
    async def cmd_help(ctx: aiomax.CommandContext):
        await ctx.send(msg.INFO, format="markdown")

    @bot.on_command("status")
    async def cmd_status(ctx: aiomax.CommandContext):
        await _show_status(ctx.user_id)
        
    @bot.on_command("test_slot")
    async def cmd_test_slot(ctx: aiomax.CommandContext):
        if str(ctx.user_id) != str(SUPERADMIN_ID):
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
    # ========== CALLBACK ==========
    @bot.on_button_callback()
    async def on_callback(callback: aiomax.types.Callback):
        try:
            await callback.answer()
        except Exception:
            pass

        user_id = callback.user_id
        payload = callback.payload
        message = callback.message

        if payload in ("info", "info_status"):
            back_payload = "back_to_status" if payload == "info_status" else "back"
            kb = aiomax.buttons.KeyboardBuilder()
            kb.add(aiomax.buttons.CallbackButton("⬅️ Назад", payload=back_payload))
            try:
                await message.edit(text=msg.INFO, format="markdown", keyboard=kb)
            except Exception:
                await bot.send_message(user_id=user_id, text=msg.INFO, format="markdown", keyboard=kb)
            return

        if payload == "back_to_status":
            await _show_status(user_id, edit_msg=message)
            return

        if payload == "back":
            pending_input.pop(str(user_id), None)
            await _show_main_menu(message, str(user_id))
            return

        if payload == "back_to_start_shift":
            pending_input.pop(str(user_id), None)
            await _handle_start_shift(user_id, edit_msg=message)
            return

        if payload == "status":
            await _show_status(user_id, edit_msg=message)
            return

        if payload == "start_shift":
            await _handle_start_shift(user_id, edit_msg=message)
            return

        if payload == "same_store":
            user_id_str = str(user_id)
            async with async_session() as session:
                user = await get_user(session, user_id_str)
                if user and user.last_store_id:
                    result = await session.execute(select(Store).where(Store.id == user.last_store_id))
                    store = result.scalar_one_or_none()
                    if store:
                        await _create_shift(user_id, store.store_code, edit_msg=message)
                        return
            return

        if payload == "new_store":
            pending_input[str(user_id)] = "store_code"
            kb = aiomax.buttons.KeyboardBuilder()
            kb.add(aiomax.buttons.CallbackButton("⬅️ Назад", payload="back_to_start_shift"))
            try:
                await message.edit(text=msg.ASK_STORE_CODE_NEW, keyboard=kb)
            except Exception:
                await bot.send_message(user_id=user_id, text=msg.ASK_STORE_CODE_NEW, keyboard=kb)
            return

        if payload == "close_shift":
            await _handle_close_shift(user_id, edit_msg=message)
            return

        if payload == "skip_closing":
            await _close_shift_without_report(user_id, edit_msg=message)
            return

    # ========== MESSAGE ==========
    @bot.on_message()
    async def on_message(message: aiomax.Message):
        user_id_str = str(message.user_id)
        text = (message.content or "").strip()

        if text.startswith("/"):
            return

        if pending_input.get(user_id_str) == "store_code":
            pending_input.pop(user_id_str, None)
            await _create_shift(message.user_id, text.strip(), edit_msg=message)
            return

        await message.reply(msg.UNKNOWN_COMMAND)