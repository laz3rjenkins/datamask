"""Общие типы ядра. Ничего не знают о форматах файлов и HTTP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Literal

CellValue = str | int | float | bool | datetime | date | time | None
CellKind = Literal["empty", "string", "number", "bool", "date", "formula", "error"]


def kind_of(value: CellValue) -> CellKind:
    if value is None or value == "":
        return "empty"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, datetime | date | time):
        return "date"
    return "string"


@dataclass(frozen=True, slots=True)
class CellRef:
    sheet: str
    row: int  # с 1
    col: int  # с 1
    value: CellValue
    kind: CellKind


@dataclass(frozen=True)
class Risk:
    code: str  # hidden_sheet, hidden_columns, comments, pivot_cache, images, external_links
    message: str  # по-русски; имена листов можно, значения ячеек нельзя
    sheet: str | None = None
    count: int = 1
