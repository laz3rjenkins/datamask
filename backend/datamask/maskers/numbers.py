from __future__ import annotations

import re
import secrets

from datamask.core.models import CellValue, EntityType
from datamask.maskers.base import MaskContext, MaskSkip

E = EntityType
_NUM = re.compile(r"(-?)(\d[\d  ]*)(?:([.,])(\d+))?")
_rnd = secrets.SystemRandom()


def apply(value: CellValue, fn: float) -> CellValue:
    """Умножает число на fn, сохраняя тип: int → int, float → 2 знака, строка → та же запись."""
    if isinstance(value, bool):
        raise MaskSkip
    if isinstance(value, int):
        return round(value * fn)
    if isinstance(value, float):
        return round(value * fn, 2)
    if isinstance(value, str):
        m = _NUM.fullmatch(value.strip())
        if not m:
            raise MaskSkip
        sign, whole, sep, frac = m.groups()
        x = float(f"{sign}{whole.replace(' ', '').replace(chr(0xA0), '')}.{frac or 0}") * fn
        out = f"{x:.{len(frac or '')}f}"
        return out.replace(".", sep) if sep else out
    raise MaskSkip


class ScaleMasker:
    """Все числа колонки × секретный коэффициент 0,5–2,0: пропорции и тренды сохраняются."""

    name = "scale"
    reversible = True
    supports = frozenset({E.AMOUNT})

    def mask(self, value: CellValue, entity: EntityType, ctx: MaskContext) -> CellValue:
        return apply(value, ctx.store.scale_factor(ctx.column_scope(), ctx.info))


class NoiseMasker:
    name = "noise"
    reversible = False
    supports = frozenset({E.AMOUNT})

    def mask(self, value: CellValue, entity: EntityType, ctx: MaskContext) -> CellValue:
        pct = float(ctx.params.get("percent", 10))
        return apply(value, 1 + _rnd.uniform(-pct, pct) / 100)
