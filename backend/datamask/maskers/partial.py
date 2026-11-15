from __future__ import annotations

from datamask.core.models import CellValue, EntityType
from datamask.core.normalize import digits, to_text
from datamask.maskers.base import MaskContext, MaskSkip

E = EntityType


def _mask_digits(s: str, keep_last: int, keep_first: int = 0) -> str:
    total = len(digits(s))
    out, i = [], 0
    for ch in s:
        if ch.isdigit():
            out.append(ch if i < keep_first or i >= total - keep_last else "*")
            i += 1
        else:
            out.append(ch)
    return "".join(out)


class PartialMasker:
    """+7 *** ***-45-67, i***@m***.ru, **** **** **** 1234."""

    name = "partial"
    reversible = False
    supports = frozenset(
        {E.PHONE, E.EMAIL, E.CARD, E.ACCOUNT, E.INN_PERSON, E.INN_ORG, E.SNILS, E.PASSPORT}
    )

    def mask(self, value: CellValue, entity: EntityType, ctx: MaskContext) -> CellValue:
        s = to_text(value)
        if entity == E.EMAIL:
            local, sep, domain = s.partition("@")
            if not sep or not local or "." not in domain:
                raise MaskSkip
            host, _, tld = domain.rpartition(".")
            return f"{local[0]}***@{host[0]}***.{tld}"
        if not digits(s):
            raise MaskSkip
        keep_last = int(ctx.params.get("keep_last", 4))
        keep_first = 1 if entity == E.PHONE and s.lstrip().startswith(("+7", "8")) else 0
        return _mask_digits(s, keep_last, keep_first)
