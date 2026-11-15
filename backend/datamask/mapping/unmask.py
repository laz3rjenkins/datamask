"""Размаскировка (SPEC §9): псевдонимы и хеши — по формату токена, фейки — как строки.

Ничего не знает о форматах файлов: работает с текстом, HTML-текстом и значениями ячеек."""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from datamask.core.models import CellValue
from datamask.mapping.store import MappingStore
from datamask.maskers.dates import parse as parse_date
from datamask.maskers.hash import PREFIXES_HASH
from datamask.maskers.numbers import apply as scale_number
from datamask.maskers.pseudonym import PREFIXES

UNKNOWN_SAMPLE = 50  # сколько неизвестных токенов перечислить в отчёте (сами токены — не данные)
_ESCAPE = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);|\\u[0-9a-fA-F]{4}")


@dataclass
class UnmaskStats:
    tokens_found: int = 0
    tokens_replaced: int = 0
    fakes_replaced: int = 0
    dates_restored: int = 0
    numbers_restored: int = 0
    unknown: Counter[str] = field(default_factory=Counter)
    missing_columns: list[str] = field(default_factory=list)  # «Лист / заголовок»

    def report(self) -> dict[str, Any]:
        return {
            "tokens_found": self.tokens_found,
            "tokens_replaced": self.tokens_replaced,
            "unknown_tokens": sum(self.unknown.values()),
            "unknown_sample": [t for t, _ in self.unknown.most_common(UNKNOWN_SAMPLE)],
            "fakes_replaced": self.fakes_replaced,
            "dates_restored": self.dates_restored,
            "numbers_restored": self.numbers_restored,
            "missing_columns": self.missing_columns,
        }


def _alternation(items: set[str]) -> str:
    # Сначала длинные: «Иванов Иван Иванович» раньше «Иванов Иван».
    return "|".join(re.escape(x) for x in sorted(items, key=len, reverse=True))


class Unmasker:
    def __init__(self, store: MappingStore) -> None:
        self.store = store
        self.stats = UnmaskStats()
        self.tokens = {e.masked: e.original for e in store.entries if e.method != "fake"}
        self.fakes = {e.masked: e.original for e in store.entries if e.method == "fake"}
        prefixes = {t.rsplit("_", 1)[0] for t in self.tokens}
        prefixes |= set(PREFIXES.values()) | set(PREFIXES_HASH.values())
        fake = f"(?P<fake>{_alternation(set(self.fakes))})|" if self.fakes else ""
        # ponytail: одна регулярка-альтернатива на все фейки; на сотнях тысяч фейков
        # компиляция станет заметной — тогда префиксное дерево вместо альтернативы.
        # Границы — по \w: «Персона_0017» не заденет часть «Персона_00170».
        self.pattern = re.compile(
            rf"(?<!\w)(?:{fake}(?P<prefix>{_alternation(prefixes)})_(?P<code>[0-9a-f]{{4,}}))(?!\w)"
        )

    def _replace(self, m: re.Match[str]) -> str:
        token = m.group()
        if m.groupdict().get("fake") is not None:  # группы нет, если фейков в таблице нет
            self.stats.fakes_replaced += 1
            return self.fakes[token]
        code = m.group("code")
        if not (code.isdigit() or len(code) >= 10):  # «Email_face» — не токен
            return token
        self.stats.tokens_found += 1
        original = self.tokens.get(token)
        if original is None:
            self.stats.unknown[token] += 1
            return token
        self.stats.tokens_replaced += 1
        return original

    def text(self, s: str) -> str:
        return self.pattern.sub(self._replace, s)

    def json_value(self, value: Any) -> Any:
        """JSON обходится по строкам (и ключам): кириллица там часто в виде \\uXXXX."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.json_value(v) for v in value]
        if isinstance(value, dict):
            return {self.text(k): self.json_value(v) for k, v in value.items()}
        return value

    def html(self, raw: str) -> str:
        """Токены ищутся и в исходном тексте, и в HTML-сущностях (&#1055;), и в \\uXXXX внутри
        скриптов: текст раскодируется с картой позиций, замены ложатся на исходные куски."""
        decoded: list[str] = []
        units: list[tuple[int, int]] = []  # для каждого раскодированного символа — его кусок
        pos = 0
        for m in _ESCAPE.finditer(raw):
            for i in range(pos, m.start()):
                decoded.append(raw[i])
                units.append((i, i + 1))
            esc = m.group()
            ch = chr(int(esc[2:], 16)) if esc.startswith("\\u") else html.unescape(esc)
            if ch == esc:  # неизвестная сущность — оставляем как есть
                for i in range(m.start(), m.end()):
                    decoded.append(raw[i])
                    units.append((i, i + 1))
            else:
                for c in ch:
                    decoded.append(c)
                    units.append((m.start(), m.end()))
            pos = m.end()
        for i in range(pos, len(raw)):
            decoded.append(raw[i])
            units.append((i, i + 1))

        out, last = [], 0
        for m in self.pattern.finditer("".join(decoded)):
            new = self._replace(m)
            if new == m.group():
                continue
            start, end = units[m.start()][0], units[m.end() - 1][1]
            piece = raw[start:end]
            if "\\u" in piece:  # внутри строки JS/JSON
                new = json.dumps(new)[1:-1]
            elif "&" in piece or any(c in new for c in "<>&"):
                new = html.escape(new, quote="&" in piece)
            out += [raw[last:start], new]
            last = end
        out.append(raw[last:])
        return "".join(out)


def restore_date(value: CellValue, days: int) -> CellValue:
    """Обратный сдвиг. MaskSkip, если значение не дата."""
    d, fmt = parse_date(value)
    back = d - timedelta(days=days)
    return back.strftime(fmt) if fmt else back


def restore_number(value: CellValue, factor: float) -> CellValue:
    """Обратное масштабирование (с точностью до округления). MaskSkip, если не число."""
    return scale_number(value, 1 / factor)
