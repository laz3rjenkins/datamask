"""XLSX. Значения — openpyxl в режиме read_only; листы и риски — прямо из XML внутри ZIP
(read_only не знает о скрытых листах/колонках, а полная загрузка большой книги медленная)."""

from __future__ import annotations

import posixpath
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree as ET  # защита от XML-бомб во входных файлах
from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.packaging.custom import CustomPropertyList
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.cell import range_boundaries

from datamask.core.models import (
    CellKind,
    CellRef,
    CellValue,
    Risk,
    SanitizePolicy,
    TextFragment,
    kind_of,
)
from datamask.formats.base import (
    HEADER_SCAN_ROWS,
    Document,
    FormatError,
    OpenOptions,
    Preview,
    RawRow,
    SheetInfo,
    build_preview,
)

REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(el: Element, name: str) -> str | None:
    """Атрибут по локальному имени (r:id и т.п. без привязки к префиксу)."""
    for k, v in el.attrib.items():
        if _local(k) == name:
            return v
    return None


@dataclass(frozen=True)
class _Rel:
    type: str  # хвост после .../relationships/
    target: str | None  # путь внутри ZIP; None для внешних ссылок


def _rels(zf: zipfile.ZipFile, part: str) -> dict[str, _Rel]:
    path = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    try:
        root = ET.fromstring(zf.read(path))
    except KeyError:
        return {}
    out = {}
    for rel in root:
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            resolved = None
        elif target.startswith("/"):
            resolved = target.lstrip("/")
        else:
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
        out[rel.get("Id", "")] = _Rel(rel.get("Type", "").rsplit("/", 1)[-1], resolved)
    return out


def _count(zf: zipfile.ZipFile, part: str | None, local: str) -> int:
    if not part:
        return 0
    try:
        root = ET.fromstring(zf.read(part))
    except KeyError:
        return 0
    return sum(1 for el in root.iter() if _local(el.tag) == local)


def _sheet_head(
    zf: zipfile.ZipFile, part: str
) -> tuple[int | None, int | None, list[tuple[int, int]]]:
    """Размер и скрытые колонки: читаем XML листа только до <sheetData>."""
    rows = cols = None
    hidden: list[tuple[int, int]] = []
    with zf.open(part) as f:
        for _, el in ET.iterparse(f, events=("start",)):
            tag = _local(el.tag)
            if tag == "sheetData":
                break
            if tag == "dimension" and el.get("ref"):
                _, _, max_col, max_row = range_boundaries(el.get("ref", ""))
                rows, cols = max_row, max_col
            elif tag == "col" and el.get("hidden") in ("1", "true"):
                hidden.append((int(el.get("min", "1")), int(el.get("max", "1"))))
    return rows, cols, hidden


def _inspect(data: bytes) -> tuple[list[SheetInfo], list[Risk]]:
    sheets: list[SheetInfo] = []
    risks: list[Risk] = []
    with zipfile.ZipFile(BytesIO(data)) as zf:
        wb_part = next(
            (r.target for r in _rels(zf, "").values() if r.type == "officeDocument" and r.target),
            "xl/workbook.xml",
        )
        wb_rels = _rels(zf, wb_part)
        root = ET.fromstring(zf.read(wb_part))
        for el in root.iter():
            if _local(el.tag) != "sheet":
                continue
            name = el.get("name", "")
            hidden_sheet = el.get("state") in ("hidden", "veryHidden")
            rel = wb_rels.get(_attr(el, "id") or "")
            if not rel or not rel.target or rel.type != "worksheet":
                continue  # лист-диаграмма и т.п.: ячеек нет
            rows, cols, hidden_cols = _sheet_head(zf, rel.target)
            sheets.append(SheetInfo(name, hidden_sheet, rows, cols, tuple(hidden_cols)))

            if hidden_sheet:
                risks.append(
                    Risk("hidden_sheet", f"Скрытый лист «{name}»: в нём тоже бывают данные", name)
                )
            n_hidden = sum(min(b, cols or b) - a + 1 for a, b in hidden_cols if a <= (cols or a))
            if n_hidden:
                risks.append(
                    Risk(
                        "hidden_columns",
                        f"Лист «{name}»: скрытые колонки ({n_hidden})",
                        name,
                        n_hidden,
                    )
                )
            sheet_rels = _rels(zf, rel.target).values()
            comments = sum(
                _count(zf, r.target, "comment") for r in sheet_rels if r.type == "comments"
            )
            if comments:
                risks.append(
                    Risk(
                        "comments",
                        f"Лист «{name}»: примечания к ячейкам ({comments}), "
                        "по умолчанию они будут удалены",
                        name,
                        comments,
                    )
                )
            images = sum(_count(zf, r.target, "pic") for r in sheet_rels if r.type == "drawing")
            if images:
                risks.append(
                    Risk(
                        "images",
                        f"Лист «{name}»: изображения ({images}). "
                        "Проверьте, нет ли сканов и подписей",
                        name,
                        images,
                    )
                )

        pivots = sum(1 for r in wb_rels.values() if r.type == "pivotCacheDefinition")
        if pivots:
            risks.append(
                Risk(
                    "pivot_cache",
                    f"Сводные таблицы ({pivots}) хранят копию исходных данных. Кэш будет удалён, "
                    "сводную нужно будет обновить в Excel",
                    None,
                    pivots,
                )
            )
        links = sum(1 for r in wb_rels.values() if r.type == "externalLink")
        if links:
            risks.append(
                Risk(
                    "external_links",
                    f"Внешние ссылки на другие файлы ({links}): в пути бывает имя пользователя",
                    None,
                    links,
                )
            )
    return sheets, risks


def _text(el: Element) -> str:
    return "".join(t.text or "" for t in el.iter() if _local(t.tag) == "t")


def _fragments(data: bytes) -> Iterator[TextFragment]:
    with zipfile.ZipFile(BytesIO(data)) as zf:
        wb_part = next(
            (r.target for r in _rels(zf, "").values() if r.type == "officeDocument" and r.target),
            "xl/workbook.xml",
        )
        wb_rels = _rels(zf, wb_part)
        for el in ET.fromstring(zf.read(wb_part)).iter():
            tag = _local(el.tag)
            if tag == "definedName" and el.get("name"):
                yield TextFragment("defined_name", el.get("name", ""))
            if tag != "sheet":
                continue
            name = el.get("name", "")
            yield TextFragment("sheet_name", name, name)
            rel = wb_rels.get(_attr(el, "id") or "")
            if not rel or not rel.target:
                continue
            for r in _rels(zf, rel.target).values():
                if r.type != "comments" or not r.target:
                    continue
                root = ET.fromstring(zf.read(r.target))
                authors = [
                    _text(a) or (a.text or "") for a in root.iter() if _local(a.tag) == "author"
                ]
                for a in authors:
                    if a.strip():
                        yield TextFragment("comment_author", a, name)
                for c in root.iter():
                    if _local(c.tag) == "comment":
                        yield TextFragment("comment", _text(c), name, c.get("ref"))


@dataclass
class XlsxDocument(Document):
    # Файл целиком в памяти: read_only-книга не держит открытый файл (Windows не дал бы удалить).
    data: bytes = b""
    workbook: Any = None  # openpyxl read_only Workbook, открывается при первом чтении
    writable: Any = None  # полная книга для маскирования (OpenOptions.writable)


def _cell(cell: Any) -> tuple[CellValue, CellKind]:
    v = cell.value
    if v is None:
        return None, "empty"
    if cell.data_type == "f":
        return (v if isinstance(v, str) else str(getattr(v, "text", v))), "formula"
    if cell.data_type == "e":
        return str(v), "error"
    return v, kind_of(v)


def _wipe_chart_caches(chart: Any) -> int:
    """Диаграммы хранят копию значений подписей и рядов (strCache/numCache)."""
    wiped = 0
    for series in getattr(chart, "series", None) or []:
        for part in (series.tx, series.cat, series.val, getattr(series, "xVal", None),
                     getattr(series, "yVal", None)):  # fmt: skip
            for ref_name in ("strRef", "numRef", "multiLvlStrRef"):
                ref = getattr(part, ref_name, None) if part is not None else None
                for cache in ("strCache", "numCache", "multiLvlStrCache"):
                    if ref is not None and getattr(ref, cache, None) is not None:
                        setattr(ref, cache, None)
                        wiped += 1
    for sub in getattr(chart, "_charts", None) or []:
        if sub is not chart:
            wiped += _wipe_chart_caches(sub)
    return wiped


class XlsxAdapter:
    extensions: tuple[str, ...] = (".xlsx",)

    def open(self, path: Path, options: OpenOptions) -> XlsxDocument:
        data = path.read_bytes()
        try:
            sheets, risks = _inspect(data)
        except (zipfile.BadZipFile, KeyError, ParseError, ValueError) as e:
            raise FormatError("Файл повреждён или это не XLSX") from e
        if not sheets:
            raise FormatError("В книге нет листов с ячейками")
        doc = XlsxDocument(path, sheets, risks, data)
        if options.writable:
            try:
                doc.writable = load_workbook(BytesIO(data))
            except Exception as e:
                raise FormatError("Файл повреждён или это не XLSX") from e
        return doc

    def sheets(self, doc: Document) -> list[SheetInfo]:
        return doc.sheets

    def risks(self, doc: Document) -> list[Risk]:
        return doc.risks

    def column_key(self, index: int) -> str:
        return str(get_column_letter(index))

    def iter_text_fragments(self, doc: Document) -> Iterator[TextFragment]:
        assert isinstance(doc, XlsxDocument)
        return _fragments(doc.data)

    def _ws(self, doc: Document, sheet: str) -> Any:
        assert isinstance(doc, XlsxDocument)
        doc.sheet(sheet)  # KeyError для неизвестного листа
        if doc.workbook is None:
            try:
                doc.workbook = load_workbook(BytesIO(doc.data), read_only=True, data_only=False)
            except Exception as e:
                raise FormatError("Файл повреждён или это не XLSX") from e
        return doc.workbook[sheet]

    def column_index(self, key: str) -> int:
        return int(column_index_from_string(key.upper()))

    def _rows(self, doc: Document, sheet: str, max_row: int | None = None) -> Iterator[RawRow]:
        for row in self._ws(doc, sheet).iter_rows(min_row=1, max_row=max_row):
            yield [_cell(c) for c in row]

    def preview(self, doc: Document, sheet: str, header_row: int | None, limit: int) -> Preview:
        raw = list(self._rows(doc, sheet, (header_row or HEADER_SCAN_ROWS) + limit))
        return build_preview(doc.sheet(sheet), raw, header_row, limit, self.column_key)

    def iter_cells(self, doc: Document, sheet: str) -> Iterator[CellRef]:
        assert isinstance(doc, XlsxDocument)
        if doc.writable is not None:
            ws = doc.writable[sheet]
            # Только существующие ячейки: iter_rows создал бы пустые на весь диапазон.
            for (r, c), cell in sorted(ws._cells.items()):
                v, k = _cell(cell)
                if k != "empty":
                    yield CellRef(sheet, r, c, v, k)
            return
        for r, row in enumerate(self._rows(doc, sheet), start=1):
            for c, (v, k) in enumerate(row, start=1):
                if k != "empty":
                    yield CellRef(sheet, r, c, v, k)

    def set_value(self, doc: Document, ref: CellRef, value: CellValue) -> None:
        assert isinstance(doc, XlsxDocument) and doc.writable is not None
        cell = doc.writable[ref.sheet].cell(ref.row, ref.col)
        cell.value = value
        if isinstance(value, str) and value.startswith("="):
            cell.data_type = "s"  # текст, а не формула
        if cell.hyperlink is not None:
            cell.hyperlink = None  # mailto: и т.п. хранят исходное значение

    def sanitize(
        self, doc: Document, policy: SanitizePolicy, mask_text: Callable[[str], str]
    ) -> list[str]:
        assert isinstance(doc, XlsxDocument) and doc.writable is not None
        wb = doc.writable
        actions = []

        props = wb.properties
        for attr in (
            "creator", "lastModifiedBy", "title", "subject", "description", "keywords",
            "category", "identifier", "contentStatus", "version", "language",
        ):  # fmt: skip
            setattr(props, attr, None)
        wb.custom_doc_props = CustomPropertyList()
        # docProps/app.xml (компания, руководитель) openpyxl пересоздаёт при сохранении
        actions.append("Метаданные очищены: автор, кто изменил, название, тема, компания")

        if policy.hidden_sheets == "remove":
            hidden = [ws for ws in wb.worksheets if ws.sheet_state != "visible"]
            if len(hidden) == len(wb.worksheets):
                hidden = hidden[1:]
            for ws in hidden:
                wb.remove(ws)
                for name in [
                    n for n, dn in wb.defined_names.items() if ws.title in str(dn.attr_text)
                ]:
                    del wb.defined_names[name]
            if hidden:
                wb.active = 0
                actions.append(f"Удалены скрытые листы: {len(hidden)}")

        comments = pivots = images = charts = 0
        for ws in wb.worksheets:
            for cell in ws._cells.values():
                if cell.comment is None:
                    continue
                comments += 1
                if policy.comments == "remove":
                    cell.comment = None
                else:
                    cell.comment = Comment(mask_text(cell.comment.text or ""), "datamask")
            if ws._pivots:
                pivots += len(ws._pivots)
                ws._pivots = []
            if policy.images == "remove" and ws._images:
                images += len(ws._images)
                ws._images = []
            for chart in ws._charts:
                charts += _wipe_chart_caches(chart)
        if comments:
            actions.append(
                f"Примечания удалены: {comments}"
                if policy.comments == "remove"
                else f"Примечания проверены как свободный текст, авторы скрыты: {comments}"
            )
        if pivots:
            actions.append(
                f"Сводные таблицы удалены вместе с кэшем исходных данных: {pivots}. "
                "Значения на их листах остались обычными ячейками, сводную нужно построить заново"
            )
        if images:
            actions.append(f"Удалены изображения: {images}")
        if charts:
            actions.append(f"Очищен кэш данных в диаграммах: {charts}")
        wb.calculation.fullCalcOnLoad = True
        actions.append("Формулы будут пересчитаны при открытии файла")
        return actions

    def save(self, doc: Document, path: Path) -> None:
        assert isinstance(doc, XlsxDocument) and doc.writable is not None
        doc.writable.save(path)
