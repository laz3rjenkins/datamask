"""Интерфейс распознавателя (SPEC §8). Новый распознаватель (NER в этапе 2) = новый файл тут."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

from datamask.core.models import EntityType, Span


@dataclass(frozen=True)
class DetectContext:
    keyword_window: int = 30  # слабым типам нужно ключевое слово в этих пределах слева


class Detector(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def entities(self) -> frozenset[EntityType]: ...
    @property
    def strength(self) -> Literal["strong", "weak"]: ...

    def detect(self, text: str, ctx: DetectContext) -> list[Span]: ...
    def match_value(self, value: str) -> float: ...


def resolve_overlaps(spans: Iterable[Span]) -> list[Span]:
    """Из пересекающихся находок выигрывает больший score, при равенстве — более длинная."""
    taken: list[Span] = []
    for s in sorted(spans, key=lambda s: (-s.score, -(s.end - s.start), s.start)):
        if all(s.end <= t.start or s.start >= t.end for t in taken):
            taken.append(s)
    return sorted(taken, key=lambda s: s.start)


def find_spans(text: str, detectors: Iterable[Detector], ctx: DetectContext) -> list[Span]:
    return resolve_overlaps(s for d in detectors for s in d.detect(text, ctx))
