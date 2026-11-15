"""Оркестрация: чтение через адаптер формата → распознавание. Маскирование и запись — M4."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from datamask.core.models import (
    ENTITY_CATEGORY,
    Category,
    CellValue,
    EntityType,
)
from datamask.detectors.base import DetectContext, Detector, find_spans
from datamask.detectors.headers import thresholds
from datamask.detectors.regex_ru import DETECTORS, CustomTermsDetector
from datamask.detectors.suggest import Suggestion, suggest_column, to_text
from datamask.formats.base import Document, FormatAdapter


def enabled_detectors(
    categories: Iterable[Category], custom_terms: Sequence[str]
) -> list[Detector]:
    """Распознаватели включённых категорий. Свой словарь — всегда, если он задан:
    пользователь сам перечислил слова, которые нужно скрыть."""
    cats = set(categories)
    dets: list[Detector] = [d for d in DETECTORS if ENTITY_CATEGORY[d.entity] in cats]
    if any(t.strip() for t in custom_terms):
        dets.append(CustomTermsDetector(custom_terms))
    return dets


@dataclass(frozen=True)
class ColumnSuggestion:
    key: str
    header: str
    suggestion: Suggestion | None
    non_empty: int  # непустых значений (без заголовка и шапки)
    formulas: int  # ячеек с формулами: при маскировании будут пропущены


@dataclass(frozen=True)
class Finding:
    entity: EntityType
    count: int


@dataclass(frozen=True)
class SheetSuggestions:
    sheet: str
    header_row: int
    columns: list[ColumnSuggestion]
    above_header: list[Finding] = field(default_factory=list)  # находки в шапке над таблицей


@dataclass(frozen=True)
class TextFinding:
    kind: str  # sheet_name, defined_name, comment, comment_author
    sheet: str | None
    ref: str | None
    entities: list[EntityType]


class _Reservoir:
    """Равномерная выборка k значений по всей колонке за один проход (алгоритм R)."""

    def __init__(self, k: int, rnd: random.Random) -> None:
        self.k, self.rnd, self.seen, self.items = k, rnd, 0, list[CellValue]()

    def add(self, value: CellValue) -> None:
        self.seen += 1
        if len(self.items) < self.k:
            self.items.append(value)
        else:
            j = self.rnd.randrange(self.seen)
            if j < self.k:
                self.items[j] = value


def _count(
    texts: Iterable[str], detectors: Sequence[Detector], ctx: DetectContext
) -> list[Finding]:
    found = Counter(s.entity for t in texts for s in find_spans(t, detectors, ctx))
    return [Finding(e, n) for e, n in found.most_common()]


def suggest_sheet(
    adapter: FormatAdapter,
    doc: Document,
    sheet: str,
    header_row: int | None,
    detectors: Sequence[Detector],
) -> SheetSuggestions:
    # ponytail: полный проход по листу (~5 с на 1 млн ячеек); если станет узким местом —
    # читать только строки выборки по известному размеру листа.
    th = thresholds()
    head = adapter.preview(doc, sheet, header_row, 1)
    hr = head.header_row
    headers = {c.index: c.header for c in head.columns}
    rnd = random.Random(0)  # noqa: S311 — выборка, не криптография; детерминизм для тестов
    samples: dict[int, _Reservoir] = {}
    formulas: Counter[int] = Counter()
    above: list[str] = []
    for cell in adapter.iter_cells(doc, sheet):
        if cell.row < hr:
            above.append(to_text(cell.value))
        elif cell.row == hr:
            continue
        elif cell.kind == "formula":
            formulas[cell.col] += 1
        elif cell.kind != "error":
            samples.setdefault(cell.col, _Reservoir(th.sample_size, rnd)).add(cell.value)

    columns = []
    for col in sorted(set(headers) | set(samples) | set(formulas)):
        sample = samples.get(col)
        header = headers.get(col, "")
        columns.append(
            ColumnSuggestion(
                key=adapter.column_key(col),
                header=header,
                suggestion=suggest_column(header, sample.items, detectors, th) if sample else None,
                non_empty=sample.seen if sample else 0,
                formulas=formulas[col],
            )
        )
    ctx = DetectContext(th.keyword_window)
    return SheetSuggestions(sheet, hr, columns, _count(above, detectors, ctx))


def scan_fragments(
    adapter: FormatAdapter, doc: Document, detectors: Sequence[Detector]
) -> list[TextFinding]:
    """Имена листов, именованные диапазоны, примечания: где нашлись данные (без самих данных)."""
    ctx = DetectContext(thresholds().keyword_window)
    out = []
    for f in adapter.iter_text_fragments(doc):
        entities = sorted({s.entity for s in find_spans(f.text, detectors, ctx)})
        if entities:
            out.append(TextFinding(f.kind, f.sheet, f.ref, entities))
    return out
