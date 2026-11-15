"""Интерфейс адаптера формата (SPEC §7). Новый формат = новый файл в formats/."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from datamask.core.models import CellKind, CellRef, CellValue, Risk

HEADER_SCAN_ROWS = 50


class FormatError(Exception):
    """Файл не читается. Сообщение показывается пользователю: без данных из файла."""


@dataclass
class OpenOptions:
    encoding: str | None = None  # CSV: None = определить автоматически
    delimiter: str | None = None


@dataclass(frozen=True)
class SheetInfo:
    name: str
    hidden: bool = False
    rows: int | None = None  # None, если формат не знает без полного чтения
    cols: int | None = None
    hidden_columns: tuple[tuple[int, int], ...] = ()  # диапазоны (с, по), с 1


@dataclass
class Document:
    path: Path
    sheets: list[SheetInfo]
    risks: list[Risk] = field(default_factory=list)

    def sheet(self, name: str) -> SheetInfo:
        for s in self.sheets:
            if s.name == name:
                return s
        raise KeyError(name)


@dataclass(frozen=True)
class Column:
    index: int  # с 1
    key: str  # как адресуется в конфиге: буква для XLSX, номер для CSV
    header: str
    hidden: bool


@dataclass(frozen=True)
class PreviewRow:
    row: int
    values: list[CellValue]
    kinds: list[CellKind]


@dataclass(frozen=True)
class Preview:
    sheet: str
    header_row: int
    detected_header_row: int
    columns: list[Column]
    above_header: list[PreviewRow]  # шапка отчёта над заголовком
    rows: list[PreviewRow]


RawRow = Sequence[tuple[CellValue, CellKind]]


class FormatAdapter(Protocol):
    extensions: tuple[str, ...]

    def open(self, path: Path, options: OpenOptions) -> Document: ...
    def sheets(self, doc: Document) -> list[SheetInfo]: ...
    def preview(self, doc: Document, sheet: str, header_row: int | None, limit: int) -> Preview: ...
    def iter_cells(self, doc: Document, sheet: str) -> Iterator[CellRef]: ...
    def risks(self, doc: Document) -> list[Risk]: ...


def detect_header_row(rows: Sequence[RawRow]) -> int:
    """Первая строка, где больше половины ячеек (по ширине таблицы) — непустые строки."""
    width = max((_last_filled(r) for r in rows), default=0)
    for i, row in enumerate(rows, start=1):
        texts = sum(1 for v, k in row if k == "string" and isinstance(v, str) and v.strip())
        if width and texts * 2 > width:
            return i
    return 1


def _last_filled(row: RawRow) -> int:
    for i in range(len(row), 0, -1):
        if row[i - 1][1] != "empty":
            return i
    return 0


def build_preview(
    info: SheetInfo,
    raw: Sequence[RawRow],
    header_row: int | None,
    limit: int,
    column_key: Callable[[int], str],
) -> Preview:
    """Общая сборка предпросмотра из первых строк листа. raw[0] — строка 1."""
    detected = detect_header_row(raw[:HEADER_SCAN_ROWS])
    header = header_row or detected
    body = raw[header : header + limit]
    width = max((_last_filled(r) for r in raw[: header + limit]), default=0)

    def pad(r: RawRow) -> list[tuple[CellValue, CellKind]]:
        cells = list(r[:width])
        return cells + [(None, "empty")] * (width - len(cells))

    def to_row(n: int, r: RawRow) -> PreviewRow:
        cells = pad(r)
        return PreviewRow(n, [v for v, _ in cells], [k for _, k in cells])

    header_cells = pad(raw[header - 1]) if header <= len(raw) else pad(())
    columns = [
        Column(
            index=i,
            key=column_key(i),
            header="" if v is None else str(v),
            hidden=any(a <= i <= b for a, b in info.hidden_columns),
        )
        for i, (v, _) in enumerate(header_cells, start=1)
    ]
    return Preview(
        sheet=info.name,
        header_row=header,
        detected_header_row=detected,
        columns=columns,
        above_header=[to_row(n, r) for n, r in enumerate(raw[: header - 1], start=1)],
        rows=[to_row(n, r) for n, r in enumerate(body, start=header + 1)],
    )
