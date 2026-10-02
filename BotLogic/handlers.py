import asyncio
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select

import aiomax
from Database.database import async_session
from Database.models import Store, User, Shift, Report
from BotLogic import messages as msg
from config import SLOTS, TIMEZONE, SUPERADMIN_ID, MAX_BOT_ID, MANAGER_WEBAPP_URL

logger = logging.getLogger(__name__)
tz = ZoneInfo(TIMEZONE)

pending_input = {}
user_locks = {}


def is_superadmin(user_id) -> bool:
    return str(user_id) == str(SUPERADMIN_ID)


def is_manager(role: str) -> bool:
    return role in ("manager", "superadmin")


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


def get_next_slot(now):
    now_min = now.hour * 60 + now.minute
    for slot in SLOTS:
        h, m = map(int, slot.split(":"))
        if h * 60 + m > now_min:
            return slot
    return None


def build_main_keyboard(has_shift: bool = False, in_status: bool = False,
                        user_role: str = "employee", user_id: str = None):
    kb = aiomax.buttons.KeyboardBuilder()
    is_super = user_id and is_superadmin(user_id)

    # Руководитель / супер-админ — меню руководителя
    if is_manager(user_role):
        kb.add(CustomWebAppButton("📊 Отчёты", bot_id=MAX_BOT_ID, url=MANAGER_WEBAPP_URL))
        kb.add(aiomax.buttons.CallbackButton("ℹ️ Инфо", payload="info_manager"))
        if is_super:
            kb.add(aiomax.buttons.CallbackButton("🔄 Роль", payload="role_menu"))
        return kb

    # Сотрудник
    if has_shift:
        if not in_status:
            kb.add(aiomax.buttons.CallbackButton("📊 Статус", payload="status"))
        kb.add(aiomax.buttons.CallbackButton("🔴 Закрыть", payload="close_shift"))
    else:
        kb.add(aiomax.buttons.CallbackButton("🟢 Смена", payload="start_shift"))

    if in_status:
        kb.add(aiomax.buttons.CallbackButton("ℹ️ Инфо", payload="info_status"))
        kb.add(aiomax.buttons.CallbackButton("⬅️ Назад", payload="back"))
    else:
        kb.add(aiomax.buttons.CallbackButton("ℹ️ Инфо", payload="info"))

    if is_super:
        kb.add(aiomax.buttons.CallbackButton("🔄 Роль", payload="role_menu"))

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


async def _delete_temp_messages(bot, user_id_str: str):
    async with async_session() as session:
        user = await get_user(session, user_id_str)
        if not user or not user.temp_messages:
            return
        try:
            ids = json.loads(user.temp_messages)
        except Exception:
            ids = []

    for mid in ids:
        try:
            await bot.delete_message(mid)
            logger.info(f"[temp] удалено {mid}")
        except Exception as e:
            logger.warning(f"[temp] не удалось удалить {mid}: {e}")

    async with async_session() as session:
        result = await session.execute(select(User).where(User.max_user_id == user_id_str))
        u = result.scalar_one_or_none()
        if u:
            u.temp_messages = None
            await session.commit()


async def render_main(bot, user_id_str: str, text: str, keyboard):
    if user_id_str not in user_locks:
        user_locks[user_id_str] = asyncio.Lock()

    async with user_locks[user_id_str]:
        await _delete_temp_messages(bot, user_id_str)

        async with async_session() as session:
            user = await get_user(session, user_id_str)
            old_main_id = user.main_message_id if user else None

        logger.info(f"[render] old={old_main_id!r}")

        if old_main_id:
            try:
                await bot.delete_message(old_main_id)
                logger.info(f"[render] удалён {old_main_id!r}")
            except Exception as e:
                logger.warning(f"[render] delete failed: {e}. Пробуем edit.")
                try:
                    await bot.edit_message(
                        old_main_id,
                        text=text,
                        format="markdown",
                        keyboard=keyboard,
                    )
                    logger.info(f"[render] отредактирован {old_main_id!r}")
                    return
                except Exception as e2:
                    logger.error(f"[render] edit failed: {e2}. Создаю новое.")

        sent = await bot.send_message(
            user_id=int(user_id_str),
            text=text,
            format="markdown",
            keyboard=keyboard,
            notify=False,
        )
        new_id = str(sent.id) if sent and getattr(sent, "id", None) else None

        if new_id:
            async with async_session() as session:
                result = await session.execute(
                    select(User).where(User.max_user_id == user_id_str)
                )
                u = result.scalar_one_or_none()
                if u:
                    u.main_message_id = new_id
                    await session.commit()
            logger.info(f"[render] создан {new_id!r}")


def setup_handlers(bot: aiomax.Bot):

    async def _send_unknown(user_id_str: str):
        kb = aiomax.buttons.KeyboardBuilder()
        kb.add(aiomax.buttons.CallbackButton("🏠 В меню", payload="back"))
        kb.add(aiomax.buttons.CallbackButton("ℹ️ Инфо", payload="info"))
        await render_main(bot, user_id_str, msg.UNKNOWN_COMMAND, kb)

    async def _show_main_menu(user_id_str: str, first_name=None, username=None):
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            if not user:
                user = User(
                    max_user_id=user_id_str,
                    role="employee",
                    first_name=first_name,
                    username=username,
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
            else:
                changed = False
                if first_name and not user.first_name:
                    user.first_name = first_name
                    changed = True
                if username and not user.username:
                    user.username = username
                    changed = True
                if changed:
                    await session.commit()

            user_role = user.role
            user_name = user.first_name or "друг"

            if is_manager(user_role):
                text = msg.GREETING_MANAGER.format(name=user_name)
                kb = build_main_keyboard(user_role=user_role, user_id=user_id_str)
                await render_main(bot, user_id_str, text, kb)
                return

            shift = await get_active_shift(session, user.id)
            store = None
            if shift:
                result = await session.execute(select(Store).where(Store.id == shift.store_id))
                store = result.scalar_one_or_none()

            if shift and store:
                text = msg.GREETING_WITH_SHIFT.format(
                    name=user_name, store_code=store.store_code,
                    address=store.address,
                    started_at=shift.started_at.strftime("%H:%M"),
                )
            else:
                text = msg.GREETING.format(name=user_name)

        kb = build_main_keyboard(has_shift=shift is not None, user_role=user_role, user_id=user_id_str)
        await render_main(bot, user_id_str, text, kb)

    async def _show_status(user_id_int: int):
        user_id_str = str(user_id_int)
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            if not user:
                return

            if is_manager(user.role):
                text = msg.MANAGER_NO_SHIFT
                kb = build_main_keyboard(user_role=user.role, user_id=user_id_str)
                await render_main(bot, user_id_str, text, kb)
                return

            shift = await get_active_shift(session, user.id)
            if not shift:
                text = msg.STATUS_NO_SHIFT
                kb = build_main_keyboard(has_shift=False, user_role=user.role, user_id=user_id_str)
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
                kb = build_main_keyboard(has_shift=True, in_status=True, user_role=user.role, user_id=user_id_str)

        await render_main(bot, user_id_str, text, kb)

    async def _create_shift(user_id_int: int, store_code: str):
        user_id_str = str(user_id_int)
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            if not user or is_manager(user.role):
                return
            result = await session.execute(select(Store).where(Store.store_code == store_code))
            store = result.scalar_one_or_none()
            if not store:
                kb = aiomax.buttons.KeyboardBuilder()
                kb.add(aiomax.buttons.CallbackButton("⬅️ Назад", payload="back_to_start_shift"))
                text = msg.STORE_NOT_FOUND.format(code=store_code)
                pending_input[user_id_str] = "store_code"
                await render_main(bot, user_id_str, text, kb)
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

        kb = build_main_keyboard(has_shift=True, user_role=user.role, user_id=user_id_str)
        await render_main(bot, user_id_str, text, kb)

    async def _handle_start_shift(user_id_int: int):
        user_id_str = str(user_id_int)
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            if not user:
                user = User(max_user_id=user_id_str, role="employee")
                session.add(user)
                await session.commit()
                await session.refresh(user)

            if is_manager(user.role):
                text = msg.MANAGER_NO_SHIFT
                kb = build_main_keyboard(user_role=user.role, user_id=user_id_str)
                await render_main(bot, user_id_str, text, kb)
                return

            shift = await get_active_shift(session, user.id)
            if shift:
                result = await session.execute(select(Store).where(Store.id == shift.store_id))
                store = result.scalar_one_or_none()
                text = msg.SHIFT_ALREADY_ACTIVE.format(
                    store_code=store.store_code, address=store.address,
                    started_at=shift.started_at.strftime("%H:%M"),
                )
                kb = build_main_keyboard(has_shift=True, user_role=user.role, user_id=user_id_str)
                await render_main(bot, user_id_str, text, kb)
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

        await render_main(bot, user_id_str, text, kb)

    async def _handle_close_shift(user_id_int: int):
        user_id_str = str(user_id_int)
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            if not user or is_manager(user.role):
                return
            shift = await get_active_shift(session, user.id)
            if not shift:
                return
            result = await session.execute(select(Store).where(Store.id == shift.store_id))
            store = result.scalar_one_or_none()

            shift.pending_closing = True
            await session.commit()

        from config import EMPLOYEE_WEBAPP_URL

        kb = aiomax.buttons.KeyboardBuilder()
        kb.add(CustomWebAppButton("📝 Отчёт", bot_id=MAX_BOT_ID, url=EMPLOYEE_WEBAPP_URL))
        kb.add(aiomax.buttons.CallbackButton("⏭ Пропустить", payload="skip_closing"))
        kb.add(aiomax.buttons.CallbackButton("⬅️ Отмена", payload="cancel_closing"))

        text = msg.CLOSING_ASK.format(store_code=store.store_code, address=store.address)
        await render_main(bot, user_id_str, text, kb)

    async def _close_shift_without_report(user_id_int: int):
        user_id_str = str(user_id_int)
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            if not user or is_manager(user.role):
                return
            shift = await get_active_shift(session, user.id)
            if not shift:
                text = msg.STATUS_NO_SHIFT
                kb = build_main_keyboard(has_shift=False, user_role=user.role, user_id=user_id_str)
                await render_main(bot, user_id_str, text, kb)
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
        kb = build_main_keyboard(has_shift=False, user_role=user.role, user_id=user_id_str)
        await render_main(bot, user_id_str, text, kb)

    # ========== МЕНЮ РОЛИ ==========
    async def _show_role_menu(user_id_str: str):
        async with async_session() as session:
            user = await get_user(session, user_id_str)
            current = user.role if user else "—"

        text = (
            f"🔄 *Смена роли*\n\n"
            f"Текущая роль: `{current}`\n\n"
            f"Выбери новую:"
        )
        kb = aiomax.buttons.KeyboardBuilder()
        kb.add(aiomax.buttons.CallbackButton("👤 Сотрудник", payload="set_role_employee"))
        kb.add(aiomax.buttons.CallbackButton("📊 Руководитель", payload="set_role_manager"))
        kb.add(aiomax.buttons.CallbackButton("👑 Супер-админ", payload="set_role_superadmin"))
        kb.add(aiomax.buttons.CallbackButton("⬅️ Назад", payload="back"))
        await render_main(bot, user_id_str, text, kb)

    # ========== START ==========
    @bot.on_bot_start()
    async def on_start(ctx: aiomax.CommandContext):
        first_name = getattr(ctx.sender, "first_name", None) if hasattr(ctx, "sender") else None
        username = getattr(ctx.sender, "username", None) if hasattr(ctx, "sender") else None
        await _show_main_menu(str(ctx.user_id), first_name=first_name, username=username)

    @bot.on_command("start")
    async def cmd_start(ctx: aiomax.CommandContext):
        first_name = getattr(ctx.sender, "first_name", None) if hasattr(ctx, "sender") else None
        username = getattr(ctx.sender, "username", None) if hasattr(ctx, "sender") else None
        await _show_main_menu(str(ctx.user_id), first_name=first_name, username=username)

    @bot.on_command("help")
    async def cmd_help(ctx: aiomax.CommandContext):
        user_id_str = str(ctx.user_id)
        async with async_session() as session:
            user = await get_user(session, user_id_str)
        if user and is_manager(user.role):
            await render_main(bot, user_id_str, msg.INFO_MANAGER, None)
        else:
            await render_main(bot, user_id_str, msg.INFO, None)

    @bot.on_command("status")
    async def cmd_status(ctx: aiomax.CommandContext):
        await _show_status(ctx.user_id)

    @bot.on_command("role")
    async def cmd_role(ctx: aiomax.CommandContext):
        user_id_str = str(ctx.user_id)
        if not is_superadmin(user_id_str):
            await _send_unknown(user_id_str)
            return
        await _show_role_menu(user_id_str)

    @bot.on_command("test_slot")
    async def cmd_test_slot(ctx: aiomax.CommandContext):
        user_id_str = str(ctx.user_id)
        if not is_superadmin(user_id_str):
            await _send_unknown(user_id_str)
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

    @bot.on_command("add_manager")
    async def cmd_add_manager(ctx: aiomax.CommandContext):
        user_id_str = str(ctx.user_id)
        if not is_superadmin(user_id_str):
            await _send_unknown(user_id_str)
            return
        if not ctx.args:
            await ctx.reply("Используй: `/add_manager <max_user_id>`")
            return

        target = ctx.args[0]
        async with async_session() as session:
            result = await session.execute(select(User).where(User.max_user_id == target))
            u = result.scalar_one_or_none()
            if u:
                u.role = "manager"
            else:
                session.add(User(max_user_id=target, role="manager"))
            await session.commit()

        await ctx.reply(f"✅ `{target}` теперь руководитель.")

    @bot.on_command("remove_manager")
    async def cmd_remove_manager(ctx: aiomax.CommandContext):
        user_id_str = str(ctx.user_id)
        if not is_superadmin(user_id_str):
            await _send_unknown(user_id_str)
            return
        if not ctx.args:
            await ctx.reply("Используй: `/remove_manager <max_user_id>`")
            return
        target = ctx.args[0]
        async with async_session() as session:
            result = await session.execute(select(User).where(User.max_user_id == target))
            u = result.scalar_one_or_none()
            if not u:
                await ctx.reply(f"❌ Пользователь `{target}` не найден.")
                return
            u.role = "employee"
            await session.commit()
        await ctx.reply(f"✅ `{target}` теперь сотрудник.")

    # ========== CALLBACK ==========
    @bot.on_button_callback()
    async def on_callback(callback: aiomax.types.Callback):
        try:
            await callback.answer()
        except Exception:
            pass

        user_id = callback.user_id
        payload = callback.payload
        user_id_str = str(user_id)

        # Смена роли
        if payload == "role_menu":
            if not is_superadmin(user_id_str):
                await _send_unknown(user_id_str)
                return
            await _show_role_menu(user_id_str)
            return

        if payload in ("set_role_employee", "set_role_manager", "set_role_superadmin"):
            if not is_superadmin(user_id_str):
                await _send_unknown(user_id_str)
                return
            role_map = {
                "set_role_employee": "employee",
                "set_role_manager": "manager",
                "set_role_superadmin": "superadmin",
            }
            new_role = role_map[payload]
            async with async_session() as session:
                user = await get_user(session, user_id_str)
                if user:
                    user.role = new_role
                    await session.commit()
            logger.info(f"[role] {user_id_str} → {new_role}")
            await _show_main_menu(user_id_str)
            return

        # Инфо
        if payload in ("info", "info_status"):
            back_payload = "back_to_status" if payload == "info_status" else "back"
            kb = aiomax.buttons.KeyboardBuilder()
            kb.add(aiomax.buttons.CallbackButton("⬅️ Назад", payload=back_payload))
            await render_main(bot, user_id_str, msg.INFO, kb)
            return

        if payload == "info_manager":
            kb = aiomax.buttons.KeyboardBuilder()
            kb.add(aiomax.buttons.CallbackButton("⬅️ Назад", payload="back"))
            await render_main(bot, user_id_str, msg.INFO_MANAGER, kb)
            return

        if payload == "back_to_status":
            await _show_status(user_id)
            return

        if payload == "back":
            pending_input.pop(user_id_str, None)
            await _show_main_menu(user_id_str)
            return

        if payload == "back_to_start_shift":
            pending_input.pop(user_id_str, None)
            await _handle_start_shift(user_id)
            return

        if payload == "status":
            await _show_status(user_id)
            return

        if payload == "start_shift":
            await _handle_start_shift(user_id)
            return

        if payload == "same_store":
            async with async_session() as session:
                user = await get_user(session, user_id_str)
                if user and not is_manager(user.role) and user.last_store_id:
                    result = await session.execute(select(Store).where(Store.id == user.last_store_id))
                    store = result.scalar_one_or_none()
                    if store:
                        await _create_shift(user_id, store.store_code)
                        return
            return

        if payload == "new_store":
            pending_input[user_id_str] = "store_code"
            kb = aiomax.buttons.KeyboardBuilder()
            kb.add(aiomax.buttons.CallbackButton("⬅️ Назад", payload="back_to_start_shift"))
            await render_main(bot, user_id_str, msg.ASK_STORE_CODE_NEW, kb)
            return

        if payload == "close_shift":
            await _handle_close_shift(user_id)
            return

        if payload == "skip_closing":
            await _close_shift_without_report(user_id)
            return

        if payload == "cancel_closing":
            async with async_session() as session:
                user = await get_user(session, user_id_str)
                if user:
                    shift = await get_active_shift(session, user.id)
                    if shift:
                        shift.pending_closing = False
                        await session.commit()
            await _show_main_menu(user_id_str)
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
            await _create_shift(message.user_id, text.strip())
            return

        await _send_unknown(user_id_str)