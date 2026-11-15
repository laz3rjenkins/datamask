"""XLSX. Значения — openpyxl в режиме read_only; листы и риски — прямо из XML внутри ZIP
(read_only не знает о скрытых листах/колонках, а полная загрузка большой книги медленная)."""

from __future__ import annotations

import posixpath
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree as ET  # защита от XML-бомб во входных файлах
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries

from datamask.core.models import CellKind, CellRef, CellValue, Risk, kind_of
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


@dataclass
class XlsxDocument(Document):
    # Файл целиком в памяти: read_only-книга не держит открытый файл (Windows не дал бы удалить).
    data: bytes = b""
    workbook: Any = None  # openpyxl read_only Workbook, открывается при первом чтении


def _cell(cell: Any) -> tuple[CellValue, CellKind]:
    v = cell.value
    if v is None:
        return None, "empty"
    if cell.data_type == "f":
        return (v if isinstance(v, str) else str(getattr(v, "text", v))), "formula"
    if cell.data_type == "e":
        return str(v), "error"
    return v, kind_of(v)


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
        return XlsxDocument(path, sheets, risks, data)

    def sheets(self, doc: Document) -> list[SheetInfo]:
        return doc.sheets

    def risks(self, doc: Document) -> list[Risk]:
        return doc.risks

    def _ws(self, doc: Document, sheet: str) -> Any:
        assert isinstance(doc, XlsxDocument)
        doc.sheet(sheet)  # KeyError для неизвестного листа
        if doc.workbook is None:
            try:
                doc.workbook = load_workbook(BytesIO(doc.data), read_only=True, data_only=False)
            except Exception as e:
                raise FormatError("Файл повреждён или это не XLSX") from e
        return doc.workbook[sheet]

    def _rows(self, doc: Document, sheet: str, max_row: int | None = None) -> Iterator[RawRow]:
        for row in self._ws(doc, sheet).iter_rows(min_row=1, max_row=max_row):
            yield [_cell(c) for c in row]

    def preview(self, doc: Document, sheet: str, header_row: int | None, limit: int) -> Preview:
        raw = list(self._rows(doc, sheet, (header_row or HEADER_SCAN_ROWS) + limit))
        return build_preview(doc.sheet(sheet), raw, header_row, limit, get_column_letter)

    def iter_cells(self, doc: Document, sheet: str) -> Iterator[CellRef]:
        for r, row in enumerate(self._rows(doc, sheet), start=1):
            for c, (v, k) in enumerate(row, start=1):
                if k != "empty":
                    yield CellRef(sheet, r, c, v, k)
