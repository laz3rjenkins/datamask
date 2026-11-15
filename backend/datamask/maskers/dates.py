from __future__ import annotations

from datetime import date, datetime, timedelta

from datamask.core.models import CellValue, EntityType
from datamask.maskers.base import MaskContext, MaskSkip

E = EntityType
FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y")  # для дат-строк (CSV): формат сохраняется


def parse(value: CellValue) -> tuple[date, str | None]:
    """Дата и формат строки (None — значение уже было датой)."""
    if isinstance(value, datetime | date):
        return value, None
    if isinstance(value, str):
        for fmt in FORMATS:
            try:
                return datetime.strptime(value.strip(), fmt).date(), fmt
            except ValueError:
                pass
    raise MaskSkip


class DateShiftMasker:
    """Все даты колонки (или файла) сдвигаются на одно и то же число дней — интервалы целы."""

    name = "date_shift"
    reversible = True
    supports = frozenset({E.BIRTH_DATE})

    def mask(self, value: CellValue, entity: EntityType, ctx: MaskContext) -> CellValue:
        d, fmt = parse(value)
        shifted = d + timedelta(days=ctx.store.date_shift(ctx.column_scope(), ctx.info))
        return shifted.strftime(fmt) if fmt else shifted


class DateGeneralizeMasker:
    """14.03.1991 → 01.03.1991 (level=month) или → 1991 (level=year)."""

    name = "date_generalize"
    reversible = False
    supports = frozenset({E.BIRTH_DATE})

    def mask(self, value: CellValue, entity: EntityType, ctx: MaskContext) -> CellValue:
        d, fmt = parse(value)
        if ctx.params.get("level", "month") == "year":
            return str(d.year) if fmt else d.year
        g = d.replace(day=1)
        return g.strftime(fmt) if fmt else g
