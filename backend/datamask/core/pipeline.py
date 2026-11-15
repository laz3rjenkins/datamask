"""Оркестрация: чтение через адаптер формата → распознавание → маскирование → очистка."""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from datamask.core.models import (
    ENTITY_CATEGORY,
    ENTITY_LABELS,
    Category,
    CellRef,
    CellValue,
    ColumnConfig,
    EntityType,
    MaskConfig,
    UserError,
)
from datamask.core.normalize import generic, normalize, to_text
from datamask.detectors.base import DetectContext, Detector, find_spans
from datamask.detectors.headers import thresholds
from datamask.detectors.regex_ru import DETECTORS, CustomTermsDetector
from datamask.detectors.suggest import Suggestion, suggest_column
from datamask.formats.base import Document, FormatAdapter
from datamask.mapping.store import MappingStore
from datamask.maskers import MASKERS, METHOD_LABELS, reversible, supported
from datamask.maskers.base import MaskContext, MaskSkip


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


# ======================= маскирование (M4) =======================

_DETECTOR_BY_ENTITY = {d.entity: d for d in DETECTORS}
_PREFIX = re.compile(r"[A-Za-zА-Яа-яЁё]{1,30}")
FREE_TEXT_WARNING = (
    "Имена и адреса внутри свободного текста в этой версии не ищутся. "
    "Просмотрите результат перед отправкой"
)


class ConfigError(UserError):
    pass


Resolved = dict[str, dict[int, ColumnConfig]]  # лист → номер колонки → настройка


def _check_params(cc: ColumnConfig, where: str) -> None:
    p = cc.params
    if "prefix" in p and not _PREFIX.fullmatch(str(p["prefix"])):
        raise ConfigError(f"{where}: префикс — только буквы, до 30 символов")
    if "keep_last" in p and not (isinstance(p["keep_last"], int) and 0 <= p["keep_last"] <= 10):
        raise ConfigError(f"{where}: keep_last — целое от 0 до 10")
    if "percent" in p and not (isinstance(p["percent"], int | float) and 0 < p["percent"] <= 50):
        raise ConfigError(f"{where}: percent — от 0 до 50")
    if p.get("level", "month") not in ("month", "year"):
        raise ConfigError(f"{where}: level — month или year")
    if p.get("scope", "column") not in ("column", "file"):
        raise ConfigError(f"{where}: scope — column или file")


def validate_config(config: MaskConfig, adapter: FormatAdapter, doc: Document) -> Resolved:
    if config.consistency_scope == "project" or config.project_id:
        raise ConfigError("Согласованность по проекту появится вместе с проектами (этап M6)")
    names = {s.name for s in doc.sheets}
    resolved: Resolved = {}
    for sheet, sc in config.sheets.items():
        if sheet not in names:
            raise ConfigError(f"Лист «{sheet}» не найден")
        cols: dict[int, ColumnConfig] = {}
        for key, cc in sc.columns.items():
            where = f"Лист «{sheet}», колонка {key}"
            try:
                idx = adapter.column_index(key)
            except ValueError:
                raise ConfigError(f"{where}: неверный адрес колонки") from None
            if not supported(cc.entity, cc.method):
                method = METHOD_LABELS.get(cc.method, cc.method)
                raise ConfigError(
                    f"{where}: способ «{method}» не подходит для типа «{ENTITY_LABELS[cc.entity]}»"
                )
            _check_params(cc, where)
            cols[idx] = cc
        resolved[sheet] = cols
    return resolved


@dataclass
class ColumnStats:
    sheet: str
    key: str
    header: str
    entity: EntityType
    method: str
    replaced: int = 0
    skipped_formulas: int = 0
    skipped_other: int = 0  # не подошло способу: дата не разобралась, нет цифр и т.п.
    unique: set[str] = field(default_factory=set, repr=False)


@dataclass
class MaskResult:
    columns: list[ColumnStats]
    text_spans: Counter[EntityType]  # фрагменты в свободном тексте, шапке, примечаниях
    outside_selected: int  # значения, найденные и заменённые вне выбранных колонок
    actions: list[str]  # что сделала очистка файла
    warnings: list[str]


class Engine:
    """Маскирует значения ячеек и фрагменты текста, ведя одну таблицу соответствий."""

    def __init__(
        self, config: MaskConfig, store: MappingStore, originals: dict[EntityType, set[str]]
    ) -> None:
        self.store = store
        self.originals = originals
        self.detectors = enabled_detectors(config.categories.enabled(), config.custom_terms)
        terms = [t for t in config.custom_terms if t.strip()]
        self.custom = CustomTermsDetector(terms) if terms else None
        self.dctx = DetectContext(thresholds().keyword_window)
        self.text_spans: Counter[EntityType] = Counter()

    def mask_value(
        self, cc: ColumnConfig, value: CellValue, scope: str, info: dict[str, str]
    ) -> CellValue:
        if cc.entity == EntityType.FREE_TEXT:
            if not isinstance(value, str):
                raise MaskSkip
            return self.mask_text(value, cc.method)
        ctx = MaskContext(self.store, cc.params, scope, info, self.originals)
        return MASKERS[cc.method].mask(value, cc.entity, ctx)

    def mask_text(
        self, text: str, method: str = "pseudonym", detectors: Sequence[Detector] | None = None
    ) -> str:
        spans = find_spans(text, self.detectors if detectors is None else detectors, self.dctx)
        for s in reversed(spans):
            out = MASKERS[method].mask(text[s.start : s.end], s.entity, MaskContext(self.store))
            text = text[: s.start] + ("" if out is None else str(out)) + text[s.end :]
            self.text_spans[s.entity] += 1
        return text


def _headers(
    adapter: FormatAdapter, doc: Document, config: MaskConfig
) -> dict[str, dict[int, str]]:
    return {
        sheet: {c.index: c.header for c in adapter.preview(doc, sheet, sc.header_row, 1).columns}
        for sheet, sc in config.sheets.items()
    }


def _collect_originals(
    adapter: FormatAdapter, doc: Document, config: MaskConfig, resolved: Resolved
) -> dict[EntityType, set[str]]:
    """Все исходные значения типов, для которых выбран фейк: фейк не должен с ними совпасть."""
    fake = {cc.entity for cols in resolved.values() for cc in cols.values() if cc.method == "fake"}
    originals: dict[EntityType, set[str]] = defaultdict(set)
    if not fake:
        return originals
    for sheet, cols in resolved.items():
        hr = config.sheets[sheet].header_row
        for cell in adapter.iter_cells(doc, sheet):
            cc = cols.get(cell.col)
            if cell.row > hr and cc and cc.entity in fake and cell.kind not in ("formula", "error"):
                originals[cc.entity].add(normalize(cc.entity, cell.value))
    return originals


def _processed(cell: CellRef, config: MaskConfig, resolved: Resolved) -> bool:
    sc = config.sheets.get(cell.sheet)
    if sc is None:
        return False
    if cell.row < sc.header_row:
        return sc.scan_above_header
    return cell.row > sc.header_row and cell.col in resolved[cell.sheet]


def _sweep(
    adapter: FormatAdapter, doc: Document, config: MaskConfig, resolved: Resolved, engine: Engine
) -> int:
    """Страховка от утечек вне выбранных колонок: ячейка, целиком равная уже замаскированному
    значению (сводная, справочный лист), получает тот же псевдоним; свой словарь — везде."""
    index: dict[str, str] = {}
    for e in engine.store.entries:
        entity = EntityType(e.entity)
        det = _DETECTOR_BY_ENTITY.get(entity)
        # только значения, действительно похожие на свой тип: не заменять везде «нет» или «-»
        if entity == EntityType.CUSTOM or (det and det.match_value(e.original) >= 0.5):
            index.setdefault(generic(e.original), e.masked)
    if not index and engine.custom is None:
        return 0
    custom = [engine.custom] if engine.custom else []
    replaced = 0
    for info in doc.sheets:
        for cell in adapter.iter_cells(doc, info.name):
            if cell.kind != "string" or not isinstance(cell.value, str):
                continue
            if _processed(cell, config, resolved):
                continue
            new = index.get(generic(cell.value))
            if new is None and custom:
                new = engine.mask_text(cell.value, "pseudonym", custom)
            if new is not None and new != cell.value:
                adapter.set_value(doc, cell, new)
                replaced += 1
    return replaced


def _warnings(
    adapter: FormatAdapter, doc: Document, stats: Sequence[ColumnStats], engine: Engine
) -> list[str]:
    out = [FREE_TEXT_WARNING]
    out += [r.message for r in doc.risks if r.code not in ("pivot_cache", "comments")]
    for st in stats:
        if st.skipped_formulas:
            out.append(
                f"Лист «{st.sheet}», колонка {st.key}: пропущено формул — {st.skipped_formulas}. "
                "Если источники замаскированы, формула даст замаскированный результат"
            )
    names = {s.name: i for i, s in enumerate(doc.sheets, start=1)}
    for f in scan_fragments(adapter, doc, engine.detectors):
        types = ", ".join(ENTITY_LABELS[e] for e in f.entities)
        if f.kind == "sheet_name":
            # само имя листа здесь — данные: называем его по номеру
            n = names.get(f.sheet or "", 0)
            out.append(f"Имя листа №{n} содержит данные ({types}): переименуйте его")
        elif f.kind == "defined_name":
            out.append(f"Имя именованного диапазона содержит данные ({types}): переименуйте его")
    return out


def run_mask(
    adapter: FormatAdapter,
    doc: Document,
    config: MaskConfig,
    store: MappingStore,
    progress: Callable[[int], None] = lambda p: None,
) -> MaskResult:
    """doc открыт с OpenOptions(writable=True). Сохранение — adapter.save() после вызова."""
    resolved = validate_config(config, adapter, doc)
    headers = _headers(adapter, doc, config)
    engine = Engine(config, store, _collect_originals(adapter, doc, config, resolved))
    progress(10)

    stats: dict[tuple[str, int], ColumnStats] = {
        (sheet, idx): ColumnStats(
            sheet, adapter.column_key(idx), headers[sheet].get(idx, ""), cc.entity, cc.method
        )
        for sheet, cols in resolved.items()
        for idx, cc in cols.items()
    }
    for i, info in enumerate(doc.sheets, start=1):
        sc = config.sheets.get(info.name)
        if sc is None:
            continue
        cols = resolved[info.name]
        for cell in adapter.iter_cells(doc, info.name):
            if cell.row < sc.header_row:
                if sc.scan_above_header and isinstance(cell.value, str):
                    new_text = engine.mask_text(cell.value)
                    if new_text != cell.value:
                        adapter.set_value(doc, cell, new_text)
                continue
            cc = cols.get(cell.col)
            if cell.row == sc.header_row or cc is None:
                continue
            st = stats[(info.name, cell.col)]
            if cell.kind == "formula":
                st.skipped_formulas += 1
                continue
            if cell.kind in ("error", "bool"):
                st.skipped_other += 1
                continue
            col_info = {"sheet": info.name, "column": st.key, "header": st.header}
            try:
                new = engine.mask_value(cc, cell.value, f"{info.name}!{st.key}", col_info)
            except MaskSkip:
                st.skipped_other += 1
                continue
            if new != cell.value:
                adapter.set_value(doc, cell, new)
                st.replaced += 1
                if cc.entity != EntityType.FREE_TEXT:
                    st.unique.add(normalize(cc.entity, cell.value))
        progress(10 + 60 * i // len(doc.sheets))

    outside = _sweep(adapter, doc, config, resolved, engine)
    progress(80)
    actions = adapter.sanitize(doc, config.sanitize, engine.mask_text)
    columns = list(stats.values())
    return MaskResult(
        columns, engine.text_spans, outside, actions, _warnings(adapter, doc, columns, engine)
    )


# ---- «до/после» ----


@dataclass(frozen=True)
class DryRunColumn:
    key: str
    header: str
    entity: EntityType | None
    method: str | None
    reversible: bool


@dataclass(frozen=True)
class DryRunRow:
    row: int
    before: list[CellValue]
    after: list[CellValue]
    changed: list[bool]


@dataclass(frozen=True)
class DryRunSheet:
    sheet: str
    header_row: int
    columns: list[DryRunColumn]
    rows: list[DryRunRow]


@dataclass(frozen=True)
class ColumnSummary:
    sheet: str
    key: str
    header: str
    entity: EntityType
    method: str
    values: int  # непустых значений, которые будут обработаны
    unique: int
    skipped_formulas: int


@dataclass(frozen=True)
class DryRun:
    sheets: list[DryRunSheet]
    summary: list[ColumnSummary]
    warnings: list[str]


def dry_run(
    adapter: FormatAdapter, doc: Document, config: MaskConfig, secret: bytes, limit: int = 50
) -> DryRun:
    """Ничего не сохраняет: временная таблица соответствий выбрасывается."""
    resolved = validate_config(config, adapter, doc)
    engine = Engine(
        config, MappingStore(secret), _collect_originals(adapter, doc, config, resolved)
    )
    sheets, summary = [], []
    for info in doc.sheets:
        sc = config.sheets.get(info.name)
        if sc is None:
            continue
        cols = resolved[info.name]
        p = adapter.preview(doc, info.name, sc.header_row, limit)
        rows = []
        for r in [*(p.above_header if sc.scan_above_header else []), *p.rows]:
            after: list[CellValue] = []
            for c, (v, k) in enumerate(zip(r.values, r.kinds, strict=True), start=1):
                cc = cols.get(c)
                new = v
                try:
                    if r.row < sc.header_row and isinstance(v, str):
                        new = engine.mask_text(v)
                    elif cc and k not in ("empty", "formula", "error", "bool"):
                        key = adapter.column_key(c)
                        new = engine.mask_value(cc, v, f"{info.name}!{key}", {})
                except MaskSkip:
                    pass
                after.append(new)
            rows.append(
                DryRunRow(
                    r.row, r.values, after, [a != b for a, b in zip(r.values, after, strict=True)]
                )
            )
        columns = [
            DryRunColumn(
                c.key,
                c.header,
                cols[c.index].entity if c.index in cols else None,
                cols[c.index].method if c.index in cols else None,
                c.index in cols and reversible(cols[c.index].method),
            )
            for c in p.columns
        ]
        sheets.append(DryRunSheet(info.name, sc.header_row, columns, rows))

        counts: Counter[int] = Counter()
        formulas: Counter[int] = Counter()
        uniques: dict[int, set[str]] = defaultdict(set)
        for cell in adapter.iter_cells(doc, info.name):
            cc = cols.get(cell.col)
            if cc is None or cell.row <= sc.header_row:
                continue
            if cell.kind == "formula":
                formulas[cell.col] += 1
            else:
                counts[cell.col] += 1
                uniques[cell.col].add(normalize(cc.entity, cell.value))
        headers = {c.index: c.header for c in p.columns}
        summary += [
            ColumnSummary(
                info.name,
                adapter.column_key(idx),
                headers.get(idx, ""),
                cc.entity,
                cc.method,
                counts[idx],
                len(uniques[idx]),
                formulas[idx],
            )
            for idx, cc in cols.items()
        ]
    warnings = [FREE_TEXT_WARNING] + [r.message for r in doc.risks]
    return DryRun(sheets, summary, warnings)
