import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from APIFolder.auth import verify_init_data
from APIFolder.notify import notify_report_sent
from Database.database import get_session
from Database.models import Store, User, Shift, Report
from config import SLOTS, TIMEZONE

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["reports"])


class ReportMetrics(BaseModel):
    revenue: int = 0
    sim_count: int = 0
    gift_sim_count: int = 0
    rev: int = 0
    zc: int = 0
    subscription: int = 0
    mnp_requests: int = 0
    combo_x2: int = 0
    accessories_sum: int = 0
    smartphones_buttons_sum: int = 0
    paid_services: int = 0
    credit_requests: int = 0


class ReportPayload(BaseModel):
    slot_time: str = Field(..., min_length=1, max_length=10)
    metrics: ReportMetrics
    is_closing: bool = False


class MePayload(BaseModel):
    init_data: str


def _extract_user(init_data: str):
    data = verify_init_data(init_data)
    if not data:
        return None, None, None
    raw = data.get("user")
    if not raw:
        return None, None, None
    try:
        obj = json.loads(raw)
    except Exception:
        return None, None, None
    if not isinstance(obj, dict) or not obj.get("id"):
        return None, None, None
    return str(obj["id"]), obj.get("first_name"), obj.get("username")


@router.post("/me")
async def get_me(payload: MePayload, session: AsyncSession = Depends(get_session)):
    max_user_id, first_name, username = _extract_user(payload.init_data)
    if not max_user_id:
        raise HTTPException(401, "Invalid initData")

    result = await session.execute(select(User).where(User.max_user_id == max_user_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(max_user_id=max_user_id, role="employee",
                    first_name=first_name, username=username)
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

    result = await session.execute(
        select(Shift).where(Shift.user_id == user.id, Shift.is_active == True)
    )
    shift = result.scalar_one_or_none()

    store_code = None
    address = None
    pending_closing = False
    shift_started_at = None

    if shift:
        result = await session.execute(select(Store).where(Store.id == shift.store_id))
        store = result.scalar_one_or_none()
        if store:
            store_code = store.store_code
            address = store.address
        pending_closing = bool(shift.pending_closing)
        shift_started_at = shift.started_at.isoformat() if shift.started_at else None

    return {
        "role": user.role,
        "max_user_id": max_user_id,
        "first_name": user.first_name,
        "store_code": store_code,
        "address": address,
        "has_active_shift": shift is not None,
        "shift_started_at": shift_started_at,
        "pending_closing": pending_closing,
    }


@router.post("/report")
async def submit_report(
    payload: ReportPayload,
    x_max_init_data: str = Header(..., alias="x-max-init-data"),
    session: AsyncSession = Depends(get_session),
):
    max_user_id, first_name, username = _extract_user(x_max_init_data)
    if not max_user_id:
        raise HTTPException(401, "Invalid initData")

    result = await session.execute(select(User).where(User.max_user_id == max_user_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(max_user_id=max_user_id, role="employee",
                    first_name=first_name, username=username)
        session.add(user)
        await session.flush()
    else:
        changed = False
        if first_name and not user.first_name:
            user.first_name = first_name
            changed = True
        if username and not user.username:
            user.username = username
            changed = True
        if changed:
            await session.flush()

    # ⛔ Руководители не могут отправлять отчёты
    if user.role not in ("employee",):
        raise HTTPException(403, "Только сотрудники могут отправлять отчёты")

    result = await session.execute(
        select(Shift).where(Shift.user_id == user.id, Shift.is_active == True)
    )
    shift = result.scalar_one_or_none()
    if not shift:
        raise HTTPException(400, "Нет активной смены")

    result = await session.execute(select(Store).where(Store.id == shift.store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(500, "Store not found")

    valid = SLOTS + ["closing"]
    if payload.slot_time not in valid:
        raise HTTPException(400, f"Invalid slot: {payload.slot_time}")

    tz = ZoneInfo(TIMEZONE)
    today = datetime.now(tz).date()

    result = await session.execute(
        select(Report).where(
            Report.store_id == store.id,
            Report.user_id == user.id,
            Report.report_date == today,
            Report.slot_time == payload.slot_time,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        await session.delete(existing)
        await session.flush()

    is_closing = (
        payload.is_closing
        or payload.slot_time == "closing"
        or shift.pending_closing
    )

    saved_message_id = shift.last_message_id
    saved_main_id = user.main_message_id

    session.add(Report(
        store_id=store.id,
        user_id=user.id,
        shift_id=shift.id,
        report_date=today,
        slot_time=payload.slot_time,
        is_closing=is_closing,
        **payload.metrics.model_dump(),
    ))

    if is_closing:
        shift.ended_at = datetime.now(tz).replace(tzinfo=None)
        shift.is_active = False
        shift.pending_closing = False
        shift.last_message_id = None

    try:
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"DB error: {e}")
        raise HTTPException(500, "Не удалось сохранить отчёт")

    logger.info(f"Report saved: {store.store_code} {payload.slot_time} closing={is_closing}")

    await notify_report_sent(
        int(max_user_id),
        is_closing=is_closing,
        notification_message_id=saved_message_id,
        main_message_id=saved_main_id,
    )

    return {"ok": True}