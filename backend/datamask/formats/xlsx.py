"""XLSX. Листы и риски — прямо из XML внутри ZIP; значения ячеек — потоковым разбором
(xlsx_stream.py), без загрузки книги в память.

Запись: openpyxl загружает «скелет» книги (листы без <sheetData>) — весит килобайты — и, как
раньше, очищает и пересобирает пакет: в результат попадают только части, которые он понимает.
Данные листов переписываются потоком из исходника и вклеиваются в листы скелета. Память не
зависит от размера листов."""

from __future__ import annotations

import posixpath
import re
import shutil
import tempfile
import zipfile
import zlib
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any
from xml.etree.ElementTree import Element, ParseError

from defusedxml import ElementTree as ET  # защита от XML-бомб во входных файлах
from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.packaging.custom import CustomPropertyList
from openpyxl.styles.stylesheet import Stylesheet
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.cell import range_boundaries
from openpyxl.utils.datetime import CALENDAR_MAC_1904, WINDOWS_EPOCH
from openpyxl.workbook.properties import CalcProperties

from datamask.core.models import (
    CellKind,
    CellRef,
    CellValue,
    Risk,
    SanitizePolicy,
    TextFragment,
)
from datamask.formats.base import (
    HEADER_SCAN_ROWS,
    Document,
    FormatError,
    OpenOptions,
    Preview,
    SheetInfo,
    build_preview,
)
from datamask.formats.xlsx_stream import (
    CHUNK,
    CellCtx,
    SharedStrings,
    SstWriter,
    StreamError,
    dimension,
    read_cells,
    rewrite_rows,
    strip_prefixes,
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


def _inspect(path: Path) -> tuple[list[SheetInfo], list[Risk]]:
    sheets: list[SheetInfo] = []
    risks: list[Risk] = []
    with zipfile.ZipFile(path) as zf:
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


def _fragments(path: Path) -> Iterator[TextFragment]:
    with zipfile.ZipFile(path) as zf:
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


def _workbook_part(zf: zipfile.ZipFile) -> str:
    return next(
        (r.target for r in _rels(zf, "").values() if r.type == "officeDocument" and r.target),
        "xl/workbook.xml",
    )


def _rels_path(part: str) -> str:
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def _sheet_parts(zf: zipfile.ZipFile) -> dict[str, str]:
    """Имя листа → путь к XML листа (только листы с ячейками)."""
    wb_part = _workbook_part(zf)
    wb_rels = _rels(zf, wb_part)
    out = {}
    for el in ET.fromstring(zf.read(wb_part)).iter():
        if _local(el.tag) == "sheet":
            rel = wb_rels.get(_attr(el, "id") or "")
            if rel and rel.target and rel.type == "worksheet":
                out[el.get("name", "")] = rel.target
    return out


def _load_ctx(zf: zipfile.ZipFile) -> CellCtx:
    """Строки книги, стили-даты и эпоха: всё, что нужно, чтобы прочитать значения ячеек."""
    wb_part = _workbook_part(zf)
    wb_rels = _rels(zf, wb_part).values()
    epoch = WINDOWS_EPOCH
    for el in ET.fromstring(zf.read(wb_part)).iter():
        if _local(el.tag) == "workbookPr" and el.get("date1904") in ("1", "true"):
            epoch = CALENDAR_MAC_1904
    sst = next((r.target for r in wb_rels if r.type == "sharedStrings" and r.target), None)
    styles_part = next((r.target for r in wb_rels if r.type == "styles" and r.target), None)
    dates: frozenset[int] = frozenset()
    timedeltas: frozenset[int] = frozenset()
    if styles_part and styles_part in zf.namelist():
        stylesheet = Stylesheet.from_tree(ET.fromstring(zf.read(styles_part)))  # type: ignore[arg-type]
        dates = frozenset(getattr(stylesheet, "date_formats", ()))
        timedeltas = frozenset(getattr(stylesheet, "timedelta_formats", ()))
    data = zf.read(sst) if sst and sst in zf.namelist() else b""
    return CellCtx(SharedStrings(data), dates, timedeltas, epoch)


_BROKEN = "Файл повреждён или это не XLSX"
_STREAM_ERRORS = (StreamError, zipfile.BadZipFile, zlib.error, EOFError, ParseError, KeyError)


@dataclass
class XlsxDocument(Document):
    # Файл не держим открытым: ZIP открывается на каждую операцию (Windows не дал бы удалить).
    parts: dict[str, str] = field(default_factory=dict)  # лист → XML листа
    ctx: CellCtx | None = None  # читается при первом обращении к ячейкам и кешируется


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
        try:
            sheets, risks = _inspect(path)
            with zipfile.ZipFile(path) as zf:
                parts = _sheet_parts(zf)
        except (zipfile.BadZipFile, KeyError, ParseError, ValueError, zlib.error) as e:
            raise FormatError(_BROKEN) from e
        if not sheets:
            raise FormatError("В книге нет листов с ячейками")
        return XlsxDocument(path, sheets, risks, parts)

    def sheets(self, doc: Document) -> list[SheetInfo]:
        return doc.sheets

    def risks(self, doc: Document) -> list[Risk]:
        return doc.risks

    def column_key(self, index: int) -> str:
        return str(get_column_letter(index))

    def column_index(self, key: str) -> int:
        return int(column_index_from_string(key.upper()))

    def iter_text_fragments(self, doc: Document) -> Iterator[TextFragment]:
        return _fragments(doc.path)

    def _ctx(self, doc: XlsxDocument, zf: zipfile.ZipFile) -> CellCtx:
        if doc.ctx is None:
            try:
                doc.ctx = _load_ctx(zf)
            except (*_STREAM_ERRORS, ValueError, TypeError) as e:
                raise FormatError(_BROKEN) from e
        return doc.ctx

    def _cells(
        self,
        doc: Document,
        sheet: str,
        max_row: int | None = None,
        translate: bool = False,
        columns: Collection[int] | None = None,
    ) -> Iterator[CellRef]:
        assert isinstance(doc, XlsxDocument)
        doc.sheet(sheet)  # KeyError для неизвестного листа
        with zipfile.ZipFile(doc.path) as zf:
            ctx = self._ctx(doc, zf)
            try:
                with zf.open(doc.parts[sheet]) as f:
                    yield from read_cells(f, sheet, ctx, max_row, translate, columns)
            except _STREAM_ERRORS as e:
                raise FormatError(_BROKEN) from e

    def preview(self, doc: Document, sheet: str, header_row: int | None, limit: int) -> Preview:
        max_row = (header_row or HEADER_SCAN_ROWS) + limit
        raw: list[list[tuple[CellValue, CellKind]]] = []
        for cell in self._cells(doc, sheet, max_row, translate=True):
            while len(raw) < cell.row:
                raw.append([])
            row = raw[cell.row - 1]
            row.extend([(None, "empty")] * (cell.col - 1 - len(row)))
            row.append((cell.value, cell.kind))
        return build_preview(doc.sheet(sheet), raw, header_row, limit, self.column_key)

    def iter_cells(
        self, doc: Document, sheet: str, columns: Collection[int] | None = None
    ) -> Iterator[CellRef]:
        return (c for c in self._cells(doc, sheet, columns=columns) if c.kind != "empty")

    def write(
        self,
        doc: Document,
        path: Path,
        transform: Callable[[CellRef], CellValue],
        policy: SanitizePolicy | None,
        mask_text: Callable[[str], str],
    ) -> list[str]:
        assert isinstance(doc, XlsxDocument)
        with (
            tempfile.TemporaryDirectory(prefix="xlsx-") as tmp_name,
            zipfile.ZipFile(doc.path) as zf,
        ):
            tmp = Path(tmp_name)
            ctx = self._ctx(doc, zf)
            try:
                _make_skeleton(zf, set(doc.parts.values()), tmp / "skeleton.xlsx")
                wb = load_workbook(tmp / "skeleton.xlsx")
            except Exception as e:
                raise FormatError(_BROKEN) from e
            if wb.calculation is None:  # в книге не было <calcPr>
                wb.calculation = CalcProperties()
            links = {
                (ws.title, c.row, c.column)
                for ws in wb.worksheets
                for c in ws._cells.values()
                if c.hyperlink is not None
            }
            data: dict[str, Path] = {}
            dims: dict[str, bytes | None] = {}
            with (tmp / "sst.part").open("wb") as sst_out:
                sst = SstWriter(ctx.sst, sst_out)
                for i, info in enumerate(doc.sheets):
                    part, name = doc.parts[info.name], info.name
                    data[name] = tmp / f"sheet{i}.part"

                    def on_change(r: int, c: int, name: str = name) -> None:
                        # гиперссылка (mailto: и т.п.) хранит исходное значение
                        if (name, r, c) in links:
                            wb[name].cell(r, c).hyperlink = None

                    try:
                        with zf.open(part) as f:
                            dims[name] = dimension(f.read(64 * 1024))
                        with zf.open(part) as f, data[name].open("wb") as out:
                            rewrite_rows(f, out, name, ctx, sst, transform, on_change)
                    except _STREAM_ERRORS as e:
                        raise FormatError(_BROKEN) from e
            actions = _sanitize(wb, policy, mask_text) if policy else []
            wb.calculation.fullCalcOnLoad = True  # кэши формул не переносятся: пересчёт
            wb.save(tmp / "out.xlsx")
            _assemble(tmp / "out.xlsx", path, data, dims, tmp / "sst.part", sst.count)
        return actions


def _make_skeleton(zf: zipfile.ZipFile, sheet_parts: set[str], dest: Path) -> None:
    """Книга без данных: листы с пустым <sheetData/> и пустая таблица строк (значений в
    скелете нет, а openpyxl разобрал бы её целиком в память)."""
    wb_part = _workbook_part(zf)
    sst = {r.target for r in _rels(zf, wb_part).values() if r.type == "sharedStrings"}
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as out:
        for item in zf.infolist():
            if item.filename in sheet_parts:
                with zf.open(item.filename) as src, out.open(item.filename, "w") as w:
                    _strip_sheet_data(src, w)
            elif item.filename in sst:
                out.writestr(item.filename, _SST_HEAD % 0 + b"</sst>")
            else:
                out.writestr(item.filename, zf.read(item.filename))


_SHEET_DATA_OPEN = re.compile(rb"<((?:[\w.-]+:)?)sheetData\b[^>]*?(/?)>")


def _strip_sheet_data(src: IO[bytes], out: IO[bytes]) -> None:
    """Копия XML листа с пустым <sheetData/>: потоком, без загрузки листа в память."""
    state, close, buf = "head", b"", b""
    while True:
        chunk = src.read(CHUNK)
        buf += chunk
        if state == "head":
            m = _SHEET_DATA_OPEN.search(buf)
            if m:
                out.write(buf[: m.start()] + b"<" + m[1] + b"sheetData/>")
                buf = buf[m.end() :]
                state = "tail" if m[2] else "skip"
                close = b"</" + m[1] + b"sheetData>"
            elif chunk:
                keep = max(len(buf) - 1024, 0)  # хвост — на случай тега на стыке кусков
                out.write(buf[:keep])
                buf = buf[keep:]
        if state == "skip":
            i = buf.find(close)
            if i >= 0:
                buf, state = buf[i + len(close) :], "tail"
            else:
                buf = buf[-len(close) :]
                if not chunk:
                    raise StreamError("sheetData not closed")
        if state == "tail" or not chunk:
            out.write(buf)
            buf = b""
        if not chunk:
            return


_SST_HEAD = (
    b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<sst xmlns="'
    b'http://schemas.openxmlformats.org/spreadsheetml/2006/main" uniqueCount="%d">'
)
_SST_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
_SHEET_DATA = re.compile(rb"<sheetData\s*/>|<sheetData\b[^>]*>.*?</sheetData>", re.S)
_DIMENSION = re.compile(rb"<dimension\b[^>]*/>")


def _assemble(
    skeleton: Path,
    dest: Path,
    data: dict[str, Path],
    dims: dict[str, bytes | None],
    sst_body: Path,
    sst_count: int,
) -> None:
    """Результат: части книги из сохранённого openpyxl скелета + потоковые данные листов +
    новая таблица строк. Листы сопоставляются по имени: openpyxl переименовывает части."""
    with zipfile.ZipFile(skeleton) as zs, zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zo:
        wb_part = _workbook_part(zs)
        sheets = {part: name for name, part in _sheet_parts(zs).items()}
        old_sst = next(
            (r.target for r in _rels(zs, wb_part).values() if r.type == "sharedStrings"), None
        )
        sst_part = old_sst or posixpath.join(posixpath.dirname(wb_part), "sharedStrings.xml")
        for item in zs.infolist():
            name = item.filename
            raw = zs.read(name)
            if name in sheets:
                _splice(zo, name, raw, data[sheets[name]], dims.get(sheets[name]))
            elif name == sst_part:
                continue
            elif old_sst is None and name == "[Content_Types].xml":
                override = f'<Override PartName="/{sst_part}" ContentType="{_SST_TYPE}"/>'
                zo.writestr(name, raw.replace(b"</Types>", override.encode() + b"</Types>"))
            elif old_sst is None and name == _rels_path(wb_part):
                rel = (
                    f'<Relationship Id="rIdDatamaskSst" Type="{REL}sharedStrings" '
                    f'Target="{posixpath.basename(sst_part)}"/>'
                )
                zo.writestr(
                    name, raw.replace(b"</Relationships>", rel.encode() + b"</Relationships>")
                )
            else:
                zo.writestr(name, raw)
        with zo.open(sst_part, "w", force_zip64=sst_body.stat().st_size > ZIP64_FROM) as w:
            w.write(_SST_HEAD % sst_count)
            with sst_body.open("rb") as f:
                shutil.copyfileobj(f, w, CHUNK)
            w.write(b"</sst>")


ZIP64_FROM = 2**31 - 2**26  # zip64 только когда без него нельзя: старые Excel его не любят


def _splice(zo: zipfile.ZipFile, name: str, xml: bytes, rows: Path, dim: bytes | None) -> None:
    m = _SHEET_DATA.search(xml)
    if not m:
        raise StreamError("sheetData not found")
    before, after = xml[: m.start()], xml[m.end() :]
    if dim:
        before = _DIMENSION.sub(lambda _: strip_prefixes(dim), before, count=1)
    with zo.open(name, "w", force_zip64=rows.stat().st_size > ZIP64_FROM) as w:
        w.write(before + b"<sheetData>")
        with rows.open("rb") as f:
            shutil.copyfileobj(f, w, CHUNK)
        w.write(b"</sheetData>" + after)


def _sanitize(wb: Any, policy: SanitizePolicy, mask_text: Callable[[str], str]) -> list[str]:
    """Очистка метаданных и скрытых мест утечки на книге openpyxl (скелете)."""
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
            for name in [n for n, dn in wb.defined_names.items() if ws.title in str(dn.attr_text)]:
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
