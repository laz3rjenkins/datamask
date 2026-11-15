"""Распознаватели на регулярных выражениях и контрольных суммах (SPEC §8)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from faker.providers.person.ru_RU import Provider as RuNames

from datamask.core.models import EntityType, Span
from datamask.core.normalize import digits
from datamask.detectors import validators as v
from datamask.detectors.base import DetectContext
from datamask.detectors.headers import context_keywords

E = EntityType


def _on_digits(check: Callable[[str], bool]) -> Callable[[str], bool]:
    return lambda s: check(digits(s))


def _valid_date(s: str) -> bool:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            datetime.strptime(s, fmt)
            return True
        except ValueError:
            pass
    return False


# ---- ФИО и адрес: только целая ячейка, в свободном тексте в v1 не ищутся (нужна NER) ----

_WORD = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
_PERSON_FULL = re.compile(rf"{_WORD}(?:\s+{_WORD}){{0,2}}")
_PERSON_SHORT = re.compile(rf"{_WORD}\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.?|[А-ЯЁ]\.\s?[А-ЯЁ]\.\s?{_WORD}")
_PATRONYMIC = re.compile(r"(?:вич|вна|ична|инична|оглы|кызы)$")
_FIRST_NAMES = frozenset(
    n.lower() for n in (*RuNames.first_names_male, *RuNames.first_names_female)
)


def person_score(value: str) -> float:
    s = " ".join(value.split())
    if _PERSON_SHORT.fullmatch(s):
        return 0.9
    if not _PERSON_FULL.fullmatch(s):
        return 0.0
    words = s.split()
    if len(words) >= 2 and any(_PATRONYMIC.search(w) for w in words):
        return 0.95
    if any(w.lower() in _FIRST_NAMES for w in words):
        return 0.8 if len(words) >= 2 else 0.5
    return 0.3 if len(words) >= 2 else 0.1


_ADDRESS_MARKERS = re.compile(
    r"(?<!\w)(?:г|ул|д|кв|пр|просп|пер|пл|наб|обл|корп|к|стр|с|п|пос|бул|ш|мкр|р-н)\."
    r"|(?<!\w)пр-т(?!\w)|(?<!\d)\d{6}(?!\d)",
    re.IGNORECASE,
)


def address_score(value: str) -> float:
    n = len(_ADDRESS_MARKERS.findall(value))
    return 0.9 if n >= 2 else 0.4 if n == 1 else 0.0


_AMOUNT = re.compile(r"-?\d[\d  ]*(?:[.,]\d+)?")


@dataclass(frozen=True)
class RegexDetector:
    name: str
    entity: EntityType
    strength: Literal["strong", "weak"]
    pattern: re.Pattern[str] | None  # поиск в тексте; None — тип ищется только целой ячейкой
    value_pattern: re.Pattern[str] | None = None  # целая ячейка; по умолчанию = pattern
    validator: Callable[[str], bool] | None = None
    scorer: Callable[[str], float] | None = None  # вместо value_pattern + validator
    score: float = 0.99
    context: tuple[str, ...] | None = field(default=None)

    @property
    def entities(self) -> frozenset[EntityType]:
        return frozenset({self.entity})

    def detect(self, text: str, ctx: DetectContext) -> list[Span]:
        if self.pattern is None or (self.strength == "weak" and self.context is None):
            return []
        low: str | None = None
        spans = []
        for m in self.pattern.finditer(text):
            if self.validator and not self.validator(m.group()):
                continue
            if self.strength == "weak" and self.context:
                low = low or text.lower().replace("ё", "е")
                left = low[max(0, m.start() - ctx.keyword_window) : m.start()]
                if not any(k in left for k in self.context):
                    continue
            spans.append(Span(m.start(), m.end(), self.entity, self.score, self.name))
        return spans

    def match_value(self, value: str) -> float:
        s = value.strip()
        if self.scorer:
            return self.scorer(s)
        pattern = self.value_pattern or self.pattern
        if pattern is None or not pattern.fullmatch(s):
            return 0.0
        return 1.0 if self.validator is None or self.validator(s) else 0.0


def _rx(p: str, flags: int = 0) -> re.Pattern[str]:
    return re.compile(p, flags)


def _d(entity: EntityType, strength: Literal["strong", "weak"], **kw: object) -> RegexDetector:
    return RegexDetector(
        name=f"regex_{entity.value.lower()}",
        entity=entity,
        strength=strength,
        context=context_keywords(entity),
        **kw,  # type: ignore[arg-type]
    )


DETECTORS: tuple[RegexDetector, ...] = (
    _d(
        E.EMAIL,
        "strong",
        pattern=_rx(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,}(?![\w-])"),
    ),
    _d(
        E.PHONE,
        "strong",
        pattern=_rx(r"(?<![\d+])(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)"),
        score=0.9,
    ),
    _d(
        E.INN_PERSON,
        "strong",
        pattern=_rx(r"(?<!\d)\d{12}(?!\d)"),
        validator=v.inn_person_ok,
    ),
    _d(E.INN_ORG, "strong", pattern=_rx(r"(?<!\d)\d{10}(?!\d)"), validator=v.inn_org_ok),
    _d(
        E.SNILS,
        "strong",
        pattern=_rx(r"(?<!\d)\d{3}[- ]?\d{3}[- ]?\d{3}[- ]?\d{2}(?!\d)"),
        validator=_on_digits(v.snils_ok),
    ),
    _d(
        E.CARD,
        "strong",
        pattern=_rx(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)"),
        validator=_on_digits(v.luhn_ok),
        score=0.95,
    ),
    _d(E.OGRN, "strong", pattern=_rx(r"(?<!\d)(?:\d{13}|\d{15})(?!\d)"), validator=v.ogrn_ok),
    _d(
        E.IP,
        "strong",
        pattern=_rx(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?!\d|\.\d)"),
        validator=v.ipv4_ok,
        score=0.9,
    ),
    _d(E.ACCOUNT, "weak", pattern=_rx(r"(?<!\d)\d{20}(?!\d)"), score=0.8),
    _d(E.PASSPORT, "weak", pattern=_rx(r"(?<!\d)\d{2} ?\d{2} ?\d{6}(?!\d)"), score=0.8),
    _d(
        E.BIRTH_DATE,
        "weak",
        pattern=_rx(r"(?<!\d)(?:\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2})(?!\d)"),
        validator=_valid_date,
        score=0.8,
    ),
    _d(
        E.ORG,
        "weak",
        # в тексте — только с кавычками-ёлочками: «ООО «Ромашка»»; ячейка — любая форма
        pattern=_rx(r"(?<!\w)(?:ООО|ОАО|ЗАО|ПАО|АО|НКО|АНО|ИП)\s+«[^«»\n]{1,80}»"),
        value_pattern=_rx(r"(?:ООО|ОАО|ЗАО|ПАО|АО|НКО|АНО|НПО|ИП|ТОО|ГУП|МУП|ФГУП)\s+\S.*"),
        score=0.85,
    ),
    _d(E.PERSON, "weak", pattern=None, scorer=person_score),
    _d(E.ADDRESS, "weak", pattern=None, scorer=address_score),
    _d(
        E.AMOUNT,
        "weak",
        pattern=None,
        scorer=lambda s: 1.0 if _AMOUNT.fullmatch(s) else 0.0,
    ),
)


class CustomTermsDetector:
    """Свой словарь (название клиента, продукта). Регистр и ё/е не важны."""

    name = "custom_terms"
    entities = frozenset({E.CUSTOM})
    strength: Literal["strong", "weak"] = "strong"

    def __init__(self, terms: Iterable[str]) -> None:
        cleaned = sorted({" ".join(t.split()) for t in terms if t.strip()}, key=len, reverse=True)

        def term_rx(t: str) -> str:
            return r"\s+".join(
                "".join("[её]" if ch in "её" else re.escape(ch) for ch in w) for w in t.split()
            )

        body = "|".join(term_rx(t.lower()) for t in cleaned)
        self._rx = re.compile(rf"(?<!\w)(?:{body})(?!\w)", re.IGNORECASE) if body else None

    def detect(self, text: str, ctx: DetectContext) -> list[Span]:
        if self._rx is None:
            return []
        return [Span(m.start(), m.end(), E.CUSTOM, 1.0, self.name) for m in self._rx.finditer(text)]

    def match_value(self, value: str) -> float:
        return 1.0 if self._rx and self._rx.fullmatch(value.strip()) else 0.0
