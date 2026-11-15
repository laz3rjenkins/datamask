"""Нормализация перед сравнением (SPEC §9 «Согласованность», п. 2)."""

from __future__ import annotations

import re
from datetime import date, datetime, time

from datamask.core.models import CellValue, EntityType

E = EntityType
_NON_DIGITS = re.compile(r"\D")
DIGIT_ENTITIES = frozenset(
    {E.INN_PERSON, E.INN_ORG, E.SNILS, E.CARD, E.ACCOUNT, E.PASSPORT, E.OGRN}
)


def digits(s: str) -> str:
    return _NON_DIGITS.sub("", s)


def to_text(value: CellValue) -> str:
    """Значение ячейки как строка: даты — ДД.ММ.ГГГГ, 7707.0 — 7707."""
    if isinstance(value, datetime | date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return "" if value is None else str(value).strip()


def generic(s: str) -> str:
    """Текст: обрезать и схлопнуть пробелы, нижний регистр, ё → е."""
    return " ".join(s.split()).lower().replace("ё", "е")


def normalize(entity: EntityType, value: CellValue) -> str:
    if isinstance(value, datetime | date):
        return value.strftime("%Y-%m-%d")
    s = to_text(value)
    if entity == E.PHONE:
        d = digits(s)
        if len(d) == 11 and d[0] in "78":
            d = d[1:]
        return "+7" + d if len(d) == 10 else generic(s)
    if entity == E.EMAIL:
        return s.strip().lower()
    if entity in DIGIT_ENTITIES:
        return digits(s) or generic(s)
    return generic(s)
