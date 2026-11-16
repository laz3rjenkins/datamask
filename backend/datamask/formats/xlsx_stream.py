"""Потоковое чтение и перезапись данных листов XLSX (<sheetData>, sharedStrings).

Ячейки разбираются регулярными выражениями прямо в распакованном потоке XML: память не
зависит от размера листа, а проход в ~15 раз быстрее openpyxl read_only. Значения и типы
совпадают с тем, что дал бы openpyxl. Структуру книги (стили, примечания, сводные и т.п.)
этот модуль не трогает — её пересобирает openpyxl в xlsx.py.
"""

from __future__ import annotations

import html
import re
from array import array
from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import IO

from openpyxl.formula.translate import Translator
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.datetime import from_excel, from_ISO8601, to_excel

from datamask.core.models import CellKind, CellRef, CellValue, kind_of

CHUNK = 4 * 2**20
CACHE_SIZE = 200_000  # декодированных строк таблицы в памяти (~десятки МБ)
_NS = rb"(?:[\w.-]+:)?"  # необязательный префикс пространства имён (<x:row> у .NET-выгрузок)
_ROW = re.compile(rb"<" + _NS + rb"row\b([^>]*?)(?:/>|>(.*?)</" + _NS + rb"row>)", re.S)
_CELL = re.compile(rb"<" + _NS + rb"c\b([^>]*?)(?:/>|>(.*?)</" + _NS + rb"c>)", re.S)
_ATTR = re.compile(rb"([\w:.-]+)\s*=\s*([\"'])(.*?)\2", re.S)
_V = re.compile(rb"<" + _NS + rb"v>(.*?)</" + _NS + rb"v>", re.S)
_F = re.compile(rb"<" + _NS + rb"f\b([^>]*?)(?:/>|>(.*?)</" + _NS + rb"f>)", re.S)
_IS = re.compile(rb"<" + _NS + rb"is>(.*?)</" + _NS + rb"is>", re.S)
_T = re.compile(rb"<" + _NS + rb"t\b[^>]*?(?:/>|>(.*?)</" + _NS + rb"t>)", re.S)
_RPH = re.compile(rb"<" + _NS + rb"rPh\b.*?</" + _NS + rb"rPh>", re.S)
_SI = re.compile(rb"<" + _NS + rb"si\b[^>]*?(?:/>|>.*?</" + _NS + rb"si>)", re.S)
_DIM = re.compile(rb"<" + _NS + rb"dimension\b[^>]*?/>")
_PREFIX = re.compile(rb"<(/?)[\w.-]+:(?=\w)")
# Символы, недопустимые в XML 1.0: в OOXML записываются как _xHHHH_
_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
# Атрибуты строки, которые понимает openpyxl. Остальные (x14ac:dyDescent и т.п.) отбрасываем:
# лист пишет openpyxl, и необъявленный префикс сломал бы XML.
_ROW_ATTR_NAMES = "r spans s customFormat ht hidden customHeight outlineLevel collapsed thickTop"
ROW_ATTRS = frozenset(n.encode() for n in (*_ROW_ATTR_NAMES.split(), "thickBot", "ph"))
_COL_CACHE: dict[bytes, int] = {}


class StreamError(ValueError):
    """Повреждённые данные листа."""


def _text(xml: bytes) -> str:
    """Текст <si>/<is>: все <t>, кроме фонетических подсказок <rPh> (как в openpyxl)."""
    if b"rPh" in xml:
        xml = _RPH.sub(b"", xml)
    return html.unescape(b"".join(_T.findall(xml)).decode("utf-8"))


def _attrs(raw: bytes) -> dict[bytes, bytes]:
    return {m[0]: m[2] for m in _ATTR.findall(raw)}


def _col(letters: bytes) -> int:
    n = _COL_CACHE.get(letters)
    if n is None:
        n = _COL_CACHE[letters] = column_index_from_string(letters.decode())
    return n


def strip_prefixes(xml: bytes) -> bytes:
    return _PREFIX.sub(rb"<\1", xml) if b":" in xml else xml


class SharedStrings:
    """Таблица строк книги: один блок байтов + смещения <si>. Строка декодируется при чтении."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.cache: dict[int, str] = {}  # повторяющиеся значения не декодируются заново
        self.starts, self.ends = array("Q"), array("Q")
        for m in _SI.finditer(data):
            self.starts.append(m.start())
            self.ends.append(m.end())

    def __len__(self) -> int:
        return len(self.starts)

    def raw(self, i: int) -> bytes:
        return self.data[self.starts[i] : self.ends[i]]

    def text(self, i: int) -> str:
        cached = self.cache.get(i)
        if cached is not None:
            return cached
        if not 0 <= i < len(self.starts):
            raise StreamError("shared string index")
        if len(self.cache) >= CACHE_SIZE:
            self.cache.clear()  # ponytail: грубое вытеснение; LRU, если кэш станет узким местом
        self.cache[i] = text = self._decode(i)
        return text

    def _decode(self, i: int) -> str:
        raw = self.data[self.starts[i] : self.ends[i]]
        # быстрый путь: <si><t>текст</t></si> без форматирования фрагментов и префиксов
        a = raw.find(b"<t")
        e = raw.rfind(b"</t>")
        if a == 4 and e > 0 and b"<r" not in raw and raw.count(b"<t") == 1:
            text = raw[raw.find(b">", a) + 1 : e].decode("utf-8")
            if "&" in text:
                text = html.unescape(text)
        else:
            text = _text(raw)
        return text.replace("x005F_", "") if "x005F_" in text else text


@dataclass(frozen=True)
class CellCtx:
    """Всё, что нужно для значения ячейки: строки книги, стили-даты, эпоха."""

    sst: SharedStrings
    date_styles: frozenset[int] = frozenset()
    timedelta_styles: frozenset[int] = frozenset()
    epoch: datetime = datetime(1899, 12, 30)


@dataclass
class _Formulas:
    """Общие формулы (t="shared"): текст зависимых ячеек выводится из первой."""

    translate: bool
    shared: dict[bytes, tuple[str, str]] = field(default_factory=dict)

    def value(self, f_attrs: bytes, f_text: bytes | None, coord: str) -> str:
        text = "=" + html.unescape(f_text.decode()) if f_text else "="
        a = _attrs(f_attrs) if b"shared" in f_attrs else {}
        if a.get(b"t") != b"shared" or b"si" not in a:
            return text
        si = a[b"si"]
        if f_text:
            self.shared[si] = (text, coord)
            return text
        if si in self.shared and self.translate:
            formula, origin = self.shared[si]
            return str(Translator(formula, origin).translate_formula(coord))
        return text


def _number(raw: bytes) -> int | float:
    s = raw.decode()
    return float(s) if "." in s or "E" in s or "e" in s else int(s)


def decode(
    s_attr: bytes | None,
    t: bytes,
    inner: bytes | None,
    ctx: CellCtx,
    formulas: _Formulas,
    r: int,
    c: int,
) -> tuple[CellValue, CellKind]:
    """Значение и тип ячейки так, как их дал бы openpyxl."""
    if not inner:
        return None, "empty"
    if inner[:3] == b"<v>" and inner[-4:] == b"</v>":  # быстрый путь: только значение
        raw = inner[3:-4]
    else:
        if b"f" in inner and (fm := _F.search(inner)):
            return formulas.value(fm[1], fm[2], f"{get_column_letter(c)}{r}"), "formula"
        if t == b"inlineStr":
            m = _IS.search(inner)
            text = _text(m[1]) if m else ""
            return (text, "string") if text else (None, "empty")
        v = _V.search(inner)
        raw = v[1] if v else b""
    if not raw:
        return None, "empty"
    try:
        if t == b"s":
            text = ctx.sst.text(int(raw))
            return (text, "string") if text else (text, "empty")
        if t == b"b":
            return bool(int(raw)), "bool"
        if t == b"e":
            return raw.decode(), "error"
        if t == b"str":
            text = html.unescape(raw.decode())
            return (text, "string") if text else (text, "empty")
        if t == b"d":
            value = from_ISO8601(raw.decode())  # type: ignore[no-untyped-call]
            return value, kind_of(value)
        n = _number(raw)
    except ValueError as e:
        raise StreamError("cell value") from e
    style = int(s_attr) if s_attr else 0
    if style in ctx.date_styles:
        try:
            d = from_excel(n, ctx.epoch, timedelta=style in ctx.timedelta_styles)
        except (OverflowError, ValueError):
            return "#VALUE!", "error"
        return d, kind_of(d)
    return n, "number"


def dimension(head: bytes) -> bytes | None:
    m = _DIM.search(head)
    return m[0] if m else None


def iter_rows(f: IO[bytes]) -> Iterator[tuple[int, bytes, bytes | None]]:
    """(номер строки, атрибуты, содержимое) каждой <row>, чтением кусками по CHUNK."""
    buf = b""
    row = 0
    while True:
        chunk = f.read(CHUNK)
        buf += chunk
        pos = 0
        for m in _ROW.finditer(buf):
            a = m[1]
            r = re.search(rb"\br\s*=\s*[\"'](\d+)", a)
            row = int(r[1]) if r else row + 1
            yield row, a, m[2]
            pos = m.end()
        buf = buf[pos:]
        if not chunk:
            return


def _quoted(a: bytes, key: bytes) -> bytes | None:
    i = a.find(key)
    if i < 0:
        return None
    i += len(key)
    return a[i : a.index(b'"', i)]


def _cell_attrs(a: bytes) -> tuple[bytes | None, bytes | None, bytes]:
    """Атрибуты r, s, t ячейки. Обычная запись ( r="A1" s="1" t="s") — поиском подстрок,
    любая другая (одинарные кавычки, переводы строк) — полным разбором."""
    if b"'" in a or b"=" in a.replace(b'="', b"") or b"\n" in a or b"\t" in a or b"\r" in a:
        d = _attrs(a)
        return d.get(b"r"), d.get(b"s"), d.get(b"t", b"n")
    return _quoted(a, b' r="'), _quoted(a, b' s="'), _quoted(a, b' t="') or b"n"


# Обычная запись ячейки (Excel, openpyxl с s до t): разбирается одной регуляркой на строку.
_FAST_CELL = re.compile(
    rb'<c r="([A-Z]{1,3})\d+"(?: s="(\d+)")?(?: t="(\w+)")?\s*(?:/>|>(.*?)</c>)', re.S
)
_CELL_OPEN = re.compile(rb"<" + _NS + rb"c\b")

# строка, колонка, буквы колонки, s, t, содержимое
Raw = tuple[int, int, bytes, bytes | None, bytes, bytes | None]


def iter_raw_cells(row: int, content: bytes | None) -> Iterator[Raw]:
    if not content:
        return
    fast = _FAST_CELL.findall(content)
    if fast and len(fast) == len(_CELL_OPEN.findall(content)):
        for letters, s_attr, t, inner in fast:
            yield row, _col(letters), letters, s_attr or None, t or b"n", inner
        return
    col = 0  # любая другая запись: порядок атрибутов, префиксы, ячейки без r
    for m in _CELL.finditer(content):
        ref, s_attr, t = _cell_attrs(m[1])
        if ref:
            letters = ref.rstrip(b"0123456789")
            col = _col(letters)
        else:
            col += 1
            letters = get_column_letter(col).encode()
        yield row, col, letters, s_attr, t, m[2]


def read_cells(
    f: IO[bytes],
    sheet: str,
    ctx: CellCtx,
    max_row: int | None = None,
    translate: bool = False,
    columns: Collection[int] | None = None,
) -> Iterator[CellRef]:
    """Все ячейки листа, включая пустые со стилем (kind="empty"), по порядку.
    columns — разбирать только эти колонки (самое дорогое — значение, а не поиск ячейки)."""
    formulas = _Formulas(translate)
    for row, _, content in iter_rows(f):
        if max_row is not None and row > max_row:
            return
        for r, c, _, s_attr, t, inner in iter_raw_cells(row, content):
            if columns is not None and c not in columns:
                continue
            value, kind = decode(s_attr, t, inner, ctx, formulas, r, c)
            yield CellRef(sheet, r, c, value, kind)


# ======================= запись =======================


def escape_text(s: str) -> bytes:
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if _ILLEGAL.search(s):
        s = _ILLEGAL.sub(lambda m: f"_x{ord(m[0]):04X}_", s)
    return s.encode("utf-8")


class SstWriter:
    """Новая таблица строк: только строки, на которые ссылается результат. Исходные значения
    замаскированных ячеек в неё не попадают. Элементы <si> пишутся сразу в файл."""

    def __init__(self, src: SharedStrings, out: IO[bytes]) -> None:
        self.src, self.out = src, out
        self.remap = array("i", [-1]) * len(src)
        self.added: dict[str, int] = {}
        self.count = 0

    def _append(self, si: bytes) -> int:
        self.out.write(si)
        self.count += 1
        return self.count - 1

    def keep(self, i: int) -> int:
        if not 0 <= i < len(self.src):
            raise StreamError("shared string index")
        j = self.remap[i]
        if j < 0:
            j = self.remap[i] = self._append(strip_prefixes(self.src.raw(i)))
        return j

    def text(self, s: str) -> int:
        j = self.added.get(s)
        if j is None:
            si = b'<si><t xml:space="preserve">' + escape_text(s) + b"</t></si>"
            j = self.added[s] = self._append(si)
        return j


def _num(x: float | int) -> bytes:
    return (str(x) if isinstance(x, int) else repr(float(x))).encode()


def _new_cell(ref: bytes, s: bytes, value: CellValue, sst: SstWriter, epoch: datetime) -> bytes:
    if value is None or value == "":
        return b'<c r="' + ref + b'"' + s + b"/>"
    if isinstance(value, bool):
        return b'<c r="' + ref + b'"' + s + b' t="b"><v>' + (b"1" if value else b"0") + b"</v></c>"
    if isinstance(value, int | float):
        return b'<c r="' + ref + b'"' + s + b"><v>" + _num(value) + b"</v></c>"
    if isinstance(value, datetime | date | time | timedelta):
        serial = to_excel(value, epoch)  # type: ignore[no-untyped-call]
        return b'<c r="' + ref + b'"' + s + b"><v>" + _num(serial) + b"</v></c>"
    idx = sst.text(str(value))
    return b'<c r="' + ref + b'"' + s + b' t="s"><v>' + str(idx).encode() + b"</v></c>"


def _kept_cell(ref: bytes, s: bytes, t: bytes, inner: bytes | None, sst: SstWriter) -> bytes:
    head = b'<c r="' + ref + b'"' + s
    if not inner:
        return head + b"/>"
    fm = _F.search(inner) if b"f" in inner else None
    if fm:
        # Кэш значения формулы не переносим: в нём бывают исходные данные. Пересчёт — при открытии.
        f_attrs = b"".join(
            b" " + k + b'="' + v + b'"' for k, v in _attrs(fm[1]).items() if b":" not in k
        )
        body = b"<f" + f_attrs + (b"/>" if fm[2] is None else b">" + fm[2] + b"</f>")
        return head + b">" + body + b"</c>"
    if t == b"inlineStr":
        m = _IS.search(inner)
        return head + b' t="inlineStr"><is>' + strip_prefixes(m[1] if m else b"") + b"</is></c>"
    v = _V.search(inner)
    if not v or not v[1]:
        return head + b"/>"
    if t == b"s":
        return head + b' t="s"><v>' + str(sst.keep(int(v[1]))).encode() + b"</v></c>"
    tt = b"" if t == b"n" else b' t="' + t + b'"'
    return head + tt + b"><v>" + v[1] + b"</v></c>"


def _row_open(row: int, raw_attrs: bytes, empty: bool) -> bytes:
    a = _attrs(raw_attrs)
    a[b"r"] = str(row).encode()
    parts = b"".join(b" " + k + b'="' + v + b'"' for k, v in a.items() if k in ROW_ATTRS)
    return b"<row" + parts + (b"/>" if empty else b">")


def rewrite_rows(
    src: IO[bytes],
    out: IO[bytes],
    sheet: str,
    ctx: CellCtx,
    sst: SstWriter,
    transform: Callable[[CellRef], CellValue],
    on_change: Callable[[int, int], None],
) -> None:
    """Пишет содержимое <sheetData> (строки без обёртки): каждая непустая ячейка проходит через
    transform; что не изменилось, переносится как было (без кэша формул и чужих атрибутов)."""
    formulas = _Formulas(translate=False)
    epoch = ctx.epoch
    parts: list[bytes] = []
    size = 0
    for row, row_attrs, content in iter_rows(src):
        parts.append(_row_open(row, row_attrs, not content))
        if not content:
            continue
        row_num = str(row).encode()
        for r, c, letters, s_attr, t, inner in iter_raw_cells(row, content):
            ref = letters + row_num
            s = b' s="' + s_attr + b'"' if s_attr else b""
            value, kind = decode(s_attr, t, inner, ctx, formulas, r, c)
            if kind == "empty":
                parts.append(_kept_cell(ref, s, t, inner, sst))
                continue
            new = transform(CellRef(sheet, r, c, value, kind))
            if new is value or new == value and type(new) is type(value):
                parts.append(_kept_cell(ref, s, t, inner, sst))
            else:
                parts.append(_new_cell(ref, s, new, sst, epoch))
                on_change(r, c)
        parts.append(b"</row>")
        size += len(content)
        if size > CHUNK:
            out.write(b"".join(parts))
            parts, size = [], 0
    out.write(b"".join(parts))
