"""Генерация Excel-отчётов для руководителя."""
import logging
from datetime import date, timedelta
from pathlib import Path
from collections import defaultdict

import pandas as pd
from sqlalchemy import select

from Database.database import async_session
from Database.models import Report, Store

logger = logging.getLogger(__name__)

EXPORTS_DIR = Path(__file__).resolve().parent.parent / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)

METRIC_LABELS = {
    "revenue": "Выручка",
    "sim_count": "Кол-во сим",
    "gift_sim_count": "Подарочные сим",
    "rev": "Rev",
    "zc": "ЗЦ",
    "subscription": "Абонемент",
    "mnp_requests": "Заявки MNP",
    "combo_x2": "Combo X2",
    "accessories_sum": "Аксессуары",
    "smartphones_buttons_sum": "Смартфоны + кнопки",
    "paid_services": "Платные услуги",
    "credit_requests": "Заявки на кредиты",
}

ALL_METRICS = list(METRIC_LABELS.keys())


async def build_excel(date_from: date, date_to: date,
                      store_codes: list[str] = None,
                      metric_keys: list[str] = None) -> Path:
    """
    Создаёт Excel-файл с листом на каждый день в периоде.
    Включает только выбранные метрики (metric_keys).
    """
    if not metric_keys:
        metric_keys = ALL_METRICS

    # оставляем только валидные
    metric_keys = [m for m in metric_keys if m in METRIC_LABELS]
    if not metric_keys:
        metric_keys = ALL_METRICS

    async with async_session() as session:
        stmt = select(Store)
        if store_codes:
            stmt = stmt.where(Store.store_code.in_(store_codes))
        result = await session.execute(stmt)
        stores = {s.id: s for s in result.scalars().all()}

        if not stores:
            raise ValueError("Нет доступных точек")

        result = await session.execute(
            select(Report).where(
                Report.report_date >= date_from,
                Report.report_date <= date_to,
                Report.store_id.in_(stores.keys()),
            )
        )
        reports = result.scalars().all()

    # {date: {store_id: {metric: sum}}}
    grouped = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    for r in reports:
        for metric in metric_keys:
            grouped[r.report_date][r.store_id][metric] += getattr(r, metric, 0) or 0

    filename = f"reports_{date_from}_{date_to}_{pd.Timestamp.now().strftime('%H%M%S')}.xlsx"
    filepath = EXPORTS_DIR / filename

    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        current = date_from
        any_data = False

        while current <= date_to:
            day_data = grouped.get(current)
            if day_data:
                any_data = True
                rows = []
                for store_id, metrics in day_data.items():
                    store = stores.get(store_id)
                    if not store:
                        continue
                    row = {"Код": store.store_code, "Адрес": store.address}
                    for m in metric_keys:
                        row[METRIC_LABELS[m]] = metrics.get(m, 0)
                    rows.append(row)

                if not rows:
                    current += timedelta(days=1)
                    continue

                df = pd.DataFrame(rows)

                # строка ИТОГО
                totals = {"Код": "", "Адрес": "ИТОГО"}
                for m in metric_keys:
                    totals[METRIC_LABELS[m]] = int(df[METRIC_LABELS[m]].sum())
                df = pd.concat([df, pd.DataFrame([totals])], ignore_index=True)

                sheet_name = current.strftime("%d.%m.%Y")
                df.to_excel(writer, sheet_name=sheet_name, index=False)

                # Авто-ширина столбцов
                ws = writer.sheets[sheet_name]
                for col_idx, col in enumerate(df.columns, start=1):
                    max_len = max(
                        df[col].astype(str).map(len).max(),
                        len(str(col)),
                    ) + 2
                    ws.column_dimensions[
                        ws.cell(row=1, column=col_idx).column_letter
                    ].width = min(max_len, 30)

            current += timedelta(days=1)

        if not any_data:
            pd.DataFrame([{"Сообщение": "Нет данных за выбранный период"}]).to_excel(
                writer, sheet_name="Пусто", index=False
            )

    logger.info(f"[Excel] Создан файл: {filepath} | metrics={metric_keys}")
    return filepath


def cleanup_old_exports(max_age_hours: int = 24):
    import time
    now = time.time()
    for f in EXPORTS_DIR.glob("*.xlsx"):
        if now - f.stat().st_mtime > max_age_hours * 3600:
            try:
                f.unlink()
            except Exception:
                pass