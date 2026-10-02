"""Эндпоинты для руководителя."""
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from APIFolder.auth import verify_init_data
from Database.database import get_session
from Database.models import Store, User
from Export.excel import build_excel, cleanup_old_exports, METRIC_LABELS, ALL_METRICS
from config import TIMEZONE

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/manager", tags=["manager"])

tz = ZoneInfo(TIMEZONE)


class ManagerPayload(BaseModel):
    init_data: str
    period: str = "today"
    date_from: str | None = None
    date_to: str | None = None
    store_codes: list[str] | None = None
    metric_keys: list[str] | None = None


class SettingsPayload(BaseModel):
    init_data: str
    metric_keys: list[str] | None = None
    store_codes: list[str] | None = None


def _extract_manager(init_data: str):
    data = verify_init_data(init_data)
    if not data:
        return None
    raw = data.get("user")
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    if not isinstance(obj, dict) or not obj.get("id"):
        return None
    return str(obj["id"])


async def _require_manager(init_data: str, session: AsyncSession):
    max_user_id = _extract_manager(init_data)
    if not max_user_id:
        raise HTTPException(401, "Invalid initData")
    result = await session.execute(select(User).where(User.max_user_id == max_user_id))
    user = result.scalar_one_or_none()
    if not user or user.role not in ("manager", "superadmin"):
        raise HTTPException(403, "Доступ только для руководителей")
    return user


def _resolve_period(payload: ManagerPayload):
    today = datetime.now(tz).date()
    if payload.period == "today":
        return today, today
    if payload.period == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if payload.period == "week":
        start = today - timedelta(days=today.weekday())
        return start, today
    if payload.period == "month":
        return today.replace(day=1), today
    if payload.period == "custom":
        if not payload.date_from or not payload.date_to:
            raise HTTPException(400, "Укажите date_from и date_to")
        return (
            datetime.strptime(payload.date_from, "%Y-%m-%d").date(),
            datetime.strptime(payload.date_to, "%Y-%m-%d").date(),
        )
    raise HTTPException(400, f"Неизвестный период: {payload.period}")


# ---------- СПРАВОЧНИКИ ----------

@router.post("/stores")
async def list_stores(
    payload: SettingsPayload,
    session: AsyncSession = Depends(get_session),
):
    await _require_manager(payload.init_data, session)
    result = await session.execute(select(Store).order_by(Store.store_code))
    stores = result.scalars().all()
    return {
        "stores": [{"code": s.store_code, "address": s.address} for s in stores]
    }


@router.post("/metrics")
async def list_metrics(
    payload: SettingsPayload,
    session: AsyncSession = Depends(get_session),
):
    """Возвращает список доступных метрик."""
    await _require_manager(payload.init_data, session)
    return {
        "metrics": [{"key": k, "label": v} for k, v in METRIC_LABELS.items()]
    }


# ---------- НАСТРОЙКИ ----------

@router.post("/settings/get")
async def get_settings(
    payload: SettingsPayload,
    session: AsyncSession = Depends(get_session),
):
    """Возвращает текущие настройки отчёта."""
    user = await _require_manager(payload.init_data, session)

    # По умолчанию — всё включено
    default = {
        "metric_keys": ALL_METRICS,
        "store_codes": None,   # None = все точки
    }

    if not user.report_settings:
        return default

    try:
        saved = json.loads(user.report_settings)
    except Exception:
        return default

    return {
        "metric_keys": saved.get("metric_keys") or ALL_METRICS,
        "store_codes": saved.get("store_codes"),
    }


@router.post("/settings/save")
async def save_settings(
    payload: SettingsPayload,
    session: AsyncSession = Depends(get_session),
):
    """Сохраняет настройки отчёта."""
    user = await _require_manager(payload.init_data, session)

    data = {
        "metric_keys": payload.metric_keys or ALL_METRICS,
        "store_codes": payload.store_codes,  # None = все
    }
    user.report_settings = json.dumps(data)
    await session.commit()

    return {"ok": True, "settings": data}


# ---------- ЭКСПОРТ ----------

@router.post("/export")
async def export_reports(
    payload: ManagerPayload,
    session: AsyncSession = Depends(get_session),
):
    user = await _require_manager(payload.init_data, session)

    date_from, date_to = _resolve_period(payload)

    if date_from > date_to:
        raise HTTPException(400, "Дата начала больше даты конца")

    if (date_to - date_from).days > 90:
        raise HTTPException(400, "Максимум 90 дней за раз")

    # Метрики: из payload, из настроек, или все
    metric_keys = payload.metric_keys
    if not metric_keys and user.report_settings:
        try:
            saved = json.loads(user.report_settings)
            metric_keys = saved.get("metric_keys")
        except Exception:
            pass
    if not metric_keys:
        metric_keys = ALL_METRICS

    # Точки: из payload, из настроек, или все
    store_codes = payload.store_codes
    if store_codes is None and user.report_settings:
        try:
            saved = json.loads(user.report_settings)
            store_codes = saved.get("store_codes")
        except Exception:
            pass

    cleanup_old_exports(max_age_hours=1)

    try:
        filepath = await build_excel(date_from, date_to, store_codes, metric_keys)
    except Exception as e:
        logger.error(f"[Manager export] {e}", exc_info=True)
        raise HTTPException(500, f"Ошибка генерации: {e}")

    return {
        "ok": True,
        "url": f"/exports/{filepath.name}",
        "filename": filepath.name,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    }