"""CSV. Все значения — строки: «007» остаётся «007», формат дат не трогаем."""

from __future__ import annotations

import codecs
import csv
import re
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass
from pathlib import Path

from charset_normalizer import from_bytes

from datamask.core.models import CellRef, CellValue, Risk, SanitizePolicy, TextFragment
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

SHEET = "CSV"
DELIMITERS = ",;\t|"
ENCODINGS = ("utf-8", "utf-8-sig", "cp1251", "koi8_r", "cp866", "utf-16")
SNIFF_CHARS = 64 * 1024

csv.field_size_limit(
    2**31 - 1
)  # длинные ячейки свободного текста; больше — OverflowError на Windows


def detect_encoding(data: bytes) -> str:
    if data.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    best = from_bytes(data, cp_isolation=["cp1251", "koi8_r", "cp866"]).best()
    return best.encoding if best else "cp1251"


def detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=DELIMITERS).delimiter
    except csv.Error:
        lines = sample.splitlines()[:20] or [""]
        # Разделитель, который есть в каждой строке; при равенстве — по порядку в DELIMITERS.
        return max(DELIMITERS, key=lambda d: min(line.count(d) for line in lines))


def detect_quote_all(sample: str, delimiter: str) -> bool:
    """Все поля в кавычках (так пишут некоторые выгрузки) — пишем так же."""
    first = next((line for line in sample.splitlines() if line.strip()), "")
    d = re.escape(delimiter)
    return bool(re.fullmatch(rf'"(?:[^"]|"")*"(?:{d}"(?:[^"]|"")*")*', first))


def detect_newline(sample: str) -> str:
    for nl in ("\r\n", "\n", "\r"):
        if nl in sample:
            return nl
    return "\n"


@dataclass
class CsvDocument(Document):
    encoding: str = "utf-8"
    delimiter: str = ","
    newline: str = "\n"  # при записи сохраняем исходные переводы строк
    quote_all: bool = False


class CsvAdapter:
    extensions: tuple[str, ...] = (".csv",)

    def open(self, path: Path, options: OpenOptions) -> CsvDocument:
        # ponytail: файл читается целиком ради проверки кодировки; для CSV в сотни МБ —
        # проверять первые мегабайты, а ошибку кодировки ловить при записи.
        data = path.read_bytes()
        encoding = options.encoding or detect_encoding(data)
        if encoding not in ENCODINGS:
            raise FormatError("Неподдерживаемая кодировка")
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError as e:
            raise FormatError("Файл не читается в выбранной кодировке") from e
        sample = text[:SNIFF_CHARS]
        if len(text) > SNIFF_CHARS and "\n" in sample:
            sample = sample[: sample.rfind("\n")]
        delimiter = options.delimiter or detect_delimiter(sample)
        if delimiter not in DELIMITERS:
            raise FormatError("Неподдерживаемый разделитель")
        sheet = SheetInfo(SHEET)
        return CsvDocument(
            path,
            [sheet],
            [],
            encoding,
            delimiter,
            detect_newline(sample),
            detect_quote_all(sample, delimiter),
        )

    def sheets(self, doc: Document) -> list[SheetInfo]:
        return doc.sheets

    def risks(self, doc: Document) -> list[Risk]:
        return doc.risks

    def column_key(self, index: int) -> str:
        return str(index)

    def column_index(self, key: str) -> int:
        n = int(key)
        if n < 1:
            raise ValueError(key)
        return n

    def write(
        self,
        doc: Document,
        path: Path,
        transform: Callable[[CellRef], CellValue],
        policy: SanitizePolicy | None,
        mask_text: Callable[[str], str],
    ) -> list[str]:
        """Построчно: та же кодировка, разделитель, кавычки и переводы строк. Метаданных и
        скрытых мест в CSV нет — очищать нечего."""
        assert isinstance(doc, CsvDocument)
        try:
            with path.open("w", encoding=doc.encoding, newline="") as out:
                w = csv.writer(
                    out,
                    delimiter=doc.delimiter,
                    lineterminator=doc.newline,
                    quoting=csv.QUOTE_ALL if doc.quote_all else csv.QUOTE_MINIMAL,
                )
                for r, row in enumerate(self._rows(doc, SHEET), start=1):
                    for c, v in enumerate(row, start=1):
                        if v:
                            new = transform(CellRef(SHEET, r, c, v, "string"))
                            row[c - 1] = "" if new is None else str(new)
                    w.writerow(row)
        except UnicodeEncodeError as e:
            raise FormatError("Замаскированное значение не записывается в кодировке файла") from e
        return []

    def iter_text_fragments(self, doc: Document) -> Iterator[TextFragment]:
        return iter(())  # в CSV текст есть только в ячейках

    def _rows(self, doc: Document, sheet: str) -> Iterator[list[str]]:
        assert isinstance(doc, CsvDocument)
        doc.sheet(sheet)
        with doc.path.open(encoding=doc.encoding, newline="") as f:
            yield from csv.reader(f, delimiter=doc.delimiter)

    def preview(self, doc: Document, sheet: str, header_row: int | None, limit: int) -> Preview:
        max_row = (header_row or HEADER_SCAN_ROWS) + limit
        raw: list[RawRow] = []
        for row in self._rows(doc, sheet):
            raw.append([(v, "string" if v else "empty") for v in row])
            if len(raw) >= max_row:
                break
        return build_preview(doc.sheet(sheet), raw, header_row, limit, self.column_key)

    def iter_cells(
        self, doc: Document, sheet: str, columns: Collection[int] | None = None
    ) -> Iterator[CellRef]:
        for r, row in enumerate(self._rows(doc, sheet), start=1):
            for c, v in enumerate(row, start=1):
                if v and (columns is None or c in columns):
                    yield CellRef(sheet, r, c, v, "string")
