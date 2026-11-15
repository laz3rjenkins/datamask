"""Загрузка файлов и предпросмотр. Имя исходного файла живёт только в памяти: в нём бывают ПДн."""

from __future__ import annotations

import logging
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PureWindowsPath
from typing import IO, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from datamask.api.errors import ApiError
from datamask.core.models import Categories, Category, EntityType, Risk, Span
from datamask.core.pipeline import (
    SheetSuggestions,
    TextFinding,
    enabled_detectors,
    scan_fragments,
    suggest_sheet,
)
from datamask.core.session import Session
from datamask.detectors.base import DetectContext, find_spans
from datamask.detectors.headers import thresholds
from datamask.formats import adapter_for
from datamask.formats.base import (
    Document,
    FormatAdapter,
    FormatError,
    OpenOptions,
    Preview,
    SheetInfo,
)
from datamask.formats.csv import CsvDocument

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/files")


@dataclass
class FileEntry:
    id: str
    original_name: str
    path: Path
    adapter: FormatAdapter
    doc: Document
    # секрет файла: фейки, хеши, сдвиг дат и масштаб в «до/после» и в результате совпадают
    secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))


@dataclass
class CsvParams:
    encoding: str
    delimiter: str


@dataclass
class FileOut:
    file_id: str
    format: Literal["xlsx", "csv"]
    sheets: list[SheetInfo]
    csv: CsvParams | None
    risks: list[Risk]
    name_findings: list[EntityType]  # что нашлось в имени файла (само имя не возвращаем)


class SuggestIn(BaseModel):
    categories: Categories = Categories()
    header_rows: dict[str, int] = {}  # лист → строка заголовка; нет — определить автоматически
    custom_terms: list[str] = []


@dataclass
class SuggestOut:
    sheets: list[SheetSuggestions]
    text_findings: list[TextFinding]


class SpansIn(BaseModel):
    """Подсветка находок в предпросмотре: шапка над заголовком и колонки «Свободный текст»."""

    header_row: int | None = Field(None, ge=1)
    columns: list[str] = []
    scan_above_header: bool = True
    categories: Categories = Categories()
    custom_terms: list[str] = []
    limit: int = Field(200, ge=1, le=1000)


@dataclass
class CellSpans:
    row: int
    col: int
    spans: list[Span]


class CsvOptionsIn(BaseModel):
    encoding: str | None = None
    delimiter: str | None = None


def _name_findings(name: str) -> list[EntityType]:
    stem = PurePath(name).stem.replace("_", " ")
    ctx = DetectContext(thresholds().keyword_window)
    return sorted({s.entity for s in find_spans(stem, enabled_detectors(list(Category), []), ctx)})


def _out(e: FileEntry) -> FileOut:
    csv = CsvParams(e.doc.encoding, e.doc.delimiter) if isinstance(e.doc, CsvDocument) else None
    return FileOut(
        e.id,
        "csv" if csv else "xlsx",
        e.adapter.sheets(e.doc),
        csv,
        e.adapter.risks(e.doc),
        _name_findings(e.original_name),
    )


def _entry(request: Request, file_id: str) -> FileEntry:
    entry: FileEntry | None = request.app.state.files.get(file_id)
    if entry is None:
        raise ApiError(404, "file_not_found", "Файл не найден. Возможно, сессия была очищена")
    return entry


def _too_large(limit: int) -> ApiError:
    return ApiError(413, "file_too_large", f"Файл больше {limit // 2**20} МБ")


def _save(src: IO[bytes], dest: Path, limit: int) -> None:
    size = 0
    with dest.open("wb") as out:
        while chunk := src.read(2**20):
            size += len(chunk)
            if size > limit:
                out.close()
                dest.unlink()
                raise _too_large(limit)
            out.write(chunk)


def _open(adapter: FormatAdapter, path: Path, options: OpenOptions) -> Document:
    try:
        return adapter.open(path, options)
    except FormatError as e:
        raise ApiError(400, "unreadable_file", str(e)) from e


@router.post("")
async def upload(request: Request) -> FileOut:
    limit: int = request.app.state.max_upload_bytes
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > limit + 64 * 1024:  # запас на обвязку multipart
        raise _too_large(limit)
    form = await request.form(max_files=1, max_fields=1)
    file = form.get("file")
    if not isinstance(file, UploadFile) or not file.filename:
        raise ApiError(400, "no_file", "Файл не передан")
    name = PureWindowsPath(file.filename).name  # отбрасываем путь с любыми разделителями
    try:
        adapter = adapter_for(name)
    except FormatError as e:
        raise ApiError(415, "unsupported_format", str(e)) from e

    session: Session = request.app.state.session
    file_id = secrets.token_hex(8)
    folder = session.path / "files" / file_id
    folder.mkdir(parents=True)
    path = folder / ("source" + PurePath(name).suffix.lower())
    try:
        await run_in_threadpool(_save, file.file, path, limit)
        doc = await run_in_threadpool(_open, adapter, path, OpenOptions())
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    entry = FileEntry(file_id, name, path, adapter, doc)
    request.app.state.files[file_id] = entry
    logger.info("Загружен файл %s: листов %d, рисков %d", file_id, len(doc.sheets), len(doc.risks))
    return _out(entry)


@router.patch("/{file_id}")
def change_csv_options(request: Request, file_id: str, body: CsvOptionsIn) -> FileOut:
    """Ручная смена кодировки и разделителя CSV (экран 1)."""
    entry = _entry(request, file_id)
    if not isinstance(entry.doc, CsvDocument):
        raise ApiError(400, "not_csv", "Кодировку и разделитель можно менять только у CSV")
    options = OpenOptions(
        body.encoding or entry.doc.encoding, body.delimiter or entry.doc.delimiter
    )
    entry.doc = _open(entry.adapter, entry.path, options)
    return _out(entry)


@router.get("/{file_id}/sheets/{sheet}/preview")
def preview(
    request: Request,
    file_id: str,
    sheet: str,
    header_row: int | None = Query(None, ge=1, le=1_048_576),
    limit: int = Query(200, ge=1, le=1000),
) -> Preview:
    entry = _entry(request, file_id)
    if sheet not in {s.name for s in entry.doc.sheets}:
        raise ApiError(404, "sheet_not_found", "Лист не найден")
    try:
        return entry.adapter.preview(entry.doc, sheet, header_row, limit)
    except FormatError as e:
        raise ApiError(400, "unreadable_file", str(e)) from e


@router.post("/{file_id}/suggest")
def suggest(request: Request, file_id: str, body: SuggestIn) -> SuggestOut:
    entry = _entry(request, file_id)
    unknown = set(body.header_rows) - {s.name for s in entry.doc.sheets}
    if unknown:
        raise ApiError(404, "sheet_not_found", "Лист не найден")
    if any(n < 1 for n in body.header_rows.values()):
        raise ApiError(422, "validation_error", "Строка заголовка должна быть не меньше 1")
    detectors = enabled_detectors(body.categories.enabled(), body.custom_terms)
    try:
        sheets = [
            suggest_sheet(entry.adapter, entry.doc, s.name, body.header_rows.get(s.name), detectors)
            for s in entry.doc.sheets
        ]
        findings = scan_fragments(entry.adapter, entry.doc, detectors)
    except FormatError as e:
        raise ApiError(400, "unreadable_file", str(e)) from e
    found = sum(1 for s in sheets for c in s.columns if c.suggestion)
    logger.info("Подсказки для %s: колонок с подсказкой %d", file_id, found)
    return SuggestOut(sheets, findings)


@router.post("/{file_id}/sheets/{sheet}/spans")
def spans(request: Request, file_id: str, sheet: str, body: SpansIn) -> list[CellSpans]:
    entry = _entry(request, file_id)
    if sheet not in {s.name for s in entry.doc.sheets}:
        raise ApiError(404, "sheet_not_found", "Лист не найден")
    try:
        cols = {entry.adapter.column_index(k) for k in body.columns}
    except ValueError:
        raise ApiError(422, "validation_error", "Неверный адрес колонки") from None
    try:
        p = entry.adapter.preview(entry.doc, sheet, body.header_row, body.limit)
    except FormatError as e:
        raise ApiError(400, "unreadable_file", str(e)) from e
    detectors = enabled_detectors(body.categories.enabled(), body.custom_terms)
    ctx = DetectContext(thresholds().keyword_window)
    cells = [
        (r.row, c, v)
        for r in (p.above_header if body.scan_above_header else [])
        for c, v in enumerate(r.values, start=1)
    ]
    cells += [(r.row, c, r.values[c - 1]) for r in p.rows for c in cols if c <= len(r.values)]
    out = []
    for row, col, value in cells:
        if isinstance(value, str) and (found := find_spans(value, detectors, ctx)):
            out.append(CellSpans(row, col, found))
    return out
