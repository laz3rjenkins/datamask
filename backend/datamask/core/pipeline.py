"""Оркестрация: чтение через адаптер формата → распознавание → маскирование → очистка."""

from __future__ import annotations

import random
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

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
from datamask.formats.base import Document, FormatAdapter, SheetInfo
from datamask.mapping.store import MappingStore
from datamask.mapping.unmask import Unmasker, UnmaskStats, restore_date, restore_number
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


STORE_METHODS = frozenset({"pseudonym", "fake", "hash"})  # пишут в таблицу соответствий


Resolved = dict[str, dict[int, ColumnConfig]]  # лист → номер колонки → настройка


def check_params(cc: ColumnConfig, where: str) -> None:
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
    if (config.consistency_scope == "project") != bool(config.project_id):
        raise ConfigError("Для согласованности по проекту выберите проект")
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
            check_params(cc, where)
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
        self.counting = True  # в первом проходе маскирования только заполняется store

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
            if self.counting:
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
    adapter: FormatAdapter,
    doc: Document,
    config: MaskConfig,
    resolved: Resolved,
    store: MappingStore,
) -> dict[EntityType, set[str]]:
    """Все исходные значения типов, для которых выбран фейк (в файле и уже известные проекту):
    фейк не должен с ними совпасть, иначе сломается размаскировка."""
    fake = {cc.entity for cols in resolved.values() for cc in cols.values() if cc.method == "fake"}
    originals: dict[EntityType, set[str]] = defaultdict(set)
    if not fake:
        return originals
    for e in store.entries:
        if (entity := EntityType(e.entity)) in fake:
            originals[entity].add(normalize(entity, e.original))
    for sheet, cols in resolved.items():
        hr = config.sheets[sheet].header_row
        wanted = {i for i, cc in cols.items() if cc.entity in fake}
        if not wanted:
            continue
        for cell in adapter.iter_cells(doc, sheet, wanted):
            cc = cols.get(cell.col)
            if cell.row > hr and cc and cell.kind not in ("formula", "error"):
                originals[cc.entity].add(normalize(cc.entity, cell.value))
    return originals


def _sweep_index(engine: Engine) -> dict[str, str]:
    """Страховка от утечек вне выбранных колонок: ячейка, целиком равная уже замаскированному
    значению (сводная, справочный лист), получает тот же псевдоним."""
    index: dict[str, str] = {}
    for e in engine.store.entries:
        entity = EntityType(e.entity)
        det = _DETECTOR_BY_ENTITY.get(entity)
        # только значения, действительно похожие на свой тип: не заменять везде «нет» или «-»
        if entity == EntityType.CUSTOM or (det and det.match_value(e.original) >= 0.5):
            index.setdefault(generic(e.original), e.masked)
    return index


def _tracker(
    progress: Callable[[int], None], sheets: Sequence[SheetInfo], lo: int, hi: int
) -> Callable[[CellRef], None]:
    """Прогресс внутри прохода по номеру строки: один огромный лист не стоит на месте."""
    offsets, total = {}, 0
    for s in sheets:
        offsets[s.name] = total
        total += max(s.rows or 1, 1)
    rows = {s.name: max(s.rows or 1, 1) for s in sheets}
    seen = 0

    def track(cell: CellRef) -> None:
        nonlocal seen
        seen += 1
        if seen % 20_000 == 0 and cell.sheet in offsets:
            done = offsets[cell.sheet] + min(cell.row, rows[cell.sheet])
            progress(lo + (hi - lo) * done // total)

    return track


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
    out: Path,
    progress: Callable[[int], None] = lambda p: None,
) -> MaskResult:
    """Пишет замаскированную копию doc в out. Два прохода по файлу, память не зависит от его
    размера: первый заполняет таблицу соответствий (нужна целиком до записи — для страховки
    вне выбранных колонок), второй пишет результат."""
    resolved = validate_config(config, adapter, doc)
    headers = _headers(adapter, doc, config)
    engine = Engine(config, store, _collect_originals(adapter, doc, config, resolved, store))
    progress(5)

    stats: dict[tuple[str, int], ColumnStats] = {}
    where: dict[tuple[str, int], tuple[str, dict[str, str]]] = {}  # область и колонка для store
    for sheet, cols in resolved.items():
        for idx, cc in cols.items():
            key = adapter.column_key(idx)
            header = headers[sheet].get(idx, "")
            stats[(sheet, idx)] = ColumnStats(sheet, key, header, cc.entity, cc.method)
            info = {
                "sheet": sheet,
                "column": key,
                "header": header,
                "header_row": str(config.sheets[sheet].header_row),
            }
            where[(sheet, idx)] = (f"{sheet}!{key}", info)

    def mask(cell: CellRef, cc: ColumnConfig) -> CellValue:
        scope, info = where[(cell.sheet, cell.col)]
        return engine.mask_value(cc, cell.value, scope, info)

    # Проход 1: только записи таблицы соответствий (псевдоним, фейк, хеш) — по ним страхуются
    # ячейки вне выбранных колонок. Остальные способы и счётчики — во втором проходе.
    engine.counting = False
    configured = [s for s in doc.sheets if s.name in config.sheets]
    track = _tracker(progress, configured, 5, 40)
    for sheet_info in configured:
        sc, cols = config.sheets[sheet_info.name], resolved[sheet_info.name]
        if sc.scan_above_header and sc.header_row > 1:
            head = adapter.preview(doc, sheet_info.name, sc.header_row, 1).above_header
            for r in head:
                for v in r.values:
                    if isinstance(v, str):
                        engine.mask_text(v)
        stored = {i: cc for i, cc in cols.items() if cc.method in STORE_METHODS}
        if not stored:
            continue
        for cell in adapter.iter_cells(doc, sheet_info.name, stored):
            track(cell)
            col_cc = stored[cell.col]
            if cell.row > sc.header_row and cell.kind not in ("formula", "error", "bool"):
                with suppress(MaskSkip):
                    mask(cell, col_cc)
    engine.counting = True
    progress(40)

    # Проход 2: запись. Псевдонимы, фейки и хеши берутся из store, остальное детерминировано.
    index = _sweep_index(engine)
    custom = [engine.custom] if engine.custom else []
    outside = 0
    track = _tracker(progress, doc.sheets, 40, 95)

    def transform(cell: CellRef) -> CellValue:
        nonlocal outside
        track(cell)
        sc = config.sheets.get(cell.sheet)
        if sc is not None:
            if cell.row < sc.header_row and sc.scan_above_header:
                return engine.mask_text(cell.value) if isinstance(cell.value, str) else cell.value
            cc = resolved[cell.sheet].get(cell.col) if cell.row > sc.header_row else None
            if cc is not None:
                st = stats[(cell.sheet, cell.col)]
                if cell.kind == "formula":
                    st.skipped_formulas += 1
                    return cell.value
                if cell.kind in ("error", "bool"):
                    st.skipped_other += 1
                    return cell.value
                try:
                    new = mask(cell, cc)
                except MaskSkip:
                    st.skipped_other += 1
                    return cell.value
                if new != cell.value:
                    st.replaced += 1
                    if cc.entity != EntityType.FREE_TEXT:
                        st.unique.add(normalize(cc.entity, cell.value))
                return new
        # вне выбранных колонок: страховка и свой словарь
        if cell.kind != "string" or not isinstance(cell.value, str):
            return cell.value
        swept = index.get(generic(cell.value))
        if swept is None and custom:
            swept = engine.mask_text(cell.value, "pseudonym", custom)
        if swept is not None and swept != cell.value:
            outside += 1
            return swept
        return cell.value

    actions = adapter.write(doc, out, transform, config.sanitize, engine.mask_text)
    progress(97)
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
    store = MappingStore(secret)
    engine = Engine(config, store, _collect_originals(adapter, doc, config, resolved, store))
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


# ======================= размаскировка таблиц (M6) =======================


@dataclass(frozen=True)
class _Restore:
    kind: Literal["date", "number"]
    param: float
    header_row: int


def _restore_targets(
    adapter: FormatAdapter, doc: Document, sheet: str, store: MappingStore, stats: UnmaskStats
) -> dict[int, _Restore]:
    """Колонки листа, где были сдвиг дат или масштаб: по листу и заголовку (колонку могли
    переставить). Лист одного листового файла (CSV) подходит под любой исходный лист."""
    single = len(doc.sheets) == 1
    wanted: list[tuple[dict[str, str], _Restore]] = []
    for kind, table, name in (
        ("date", store.date_shifts, "days"),
        ("number", store.scale_factors, "factor"),
    ):
        for item in table.values():
            for info in item.get("columns", []):
                if info.get("sheet") == sheet or single:
                    hr = int(info.get("header_row") or 1)
                    wanted.append((info, _Restore(kind, float(item[name]), hr)))  # type: ignore[arg-type]
    if not wanted:
        return {}
    rows_needed = {r.header_row for _, r in wanted}
    headers: dict[int, dict[int, str]] = defaultdict(dict)  # строка → колонка → заголовок
    for cell in adapter.iter_cells(doc, sheet):
        if cell.row > max(rows_needed):
            break
        if cell.row in rows_needed:
            headers[cell.row][cell.col] = to_text(cell.value)
    out: dict[int, _Restore] = {}
    for info, r in wanted:
        row = headers.get(r.header_row, {})
        header = info.get("header", "").strip()
        try:
            col: int | None = adapter.column_index(info.get("column", ""))
        except ValueError:
            col = None
        if col is None or row.get(col, "") != header:
            col = next((c for c, h in sorted(row.items()) if h == header and header), None)
        if col is None:
            stats.missing_columns.append(
                f"{info.get('sheet', '')} / {header or info.get('column')}"
            )
        else:
            out[col] = r
    return out


def run_unmask_table(
    adapter: FormatAdapter,
    doc: Document,
    unmasker: Unmasker,
    out: Path,
    progress: Callable[[int], None] = lambda p: None,
) -> UnmaskStats:
    """Пишет в out копию doc с настоящими значениями."""
    stats = unmasker.stats
    targets = {
        info.name: _restore_targets(adapter, doc, info.name, unmasker.store, stats)
        for info in doc.sheets
    }
    track = _tracker(progress, doc.sheets, 20, 95)

    def transform(cell: CellRef) -> CellValue:
        track(cell)
        t = targets[cell.sheet].get(cell.col)
        if t and cell.row > t.header_row and cell.kind in ("date", "number", "string"):
            try:
                if t.kind == "date":
                    new = restore_date(cell.value, int(t.param))
                    stats.dates_restored += 1
                else:
                    new = restore_number(cell.value, t.param)
                    stats.numbers_restored += 1
                return new
            except MaskSkip:
                return cell.value
        if cell.kind == "string" and isinstance(cell.value, str):
            return unmasker.text(cell.value)
        return cell.value

    adapter.write(doc, out, transform, None, lambda text: text)
    return stats
