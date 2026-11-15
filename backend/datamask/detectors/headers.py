"""Словари заголовков и пороги из rules.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from datamask.core.models import EntityType

RULES_PATH = Path(__file__).with_name("rules.yaml")


@dataclass(frozen=True)
class Thresholds:
    sample_size: int
    match_value_min: float
    strong_value_share: float
    strong_with_header_share: float
    weak_with_header_share: float
    free_text_min_avg_len: float
    keyword_window: int


def normalize_header(text: str) -> list[str]:
    return re.sub(r"[^\w]+|_", " ", text.lower().replace("ё", "е")).split()


@cache
def _rules() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return data


@cache
def thresholds() -> Thresholds:
    return Thresholds(**_rules()["thresholds"])


@cache
def _header_keywords(entity: EntityType) -> tuple[tuple[str, ...], ...]:
    words = _rules()["entities"].get(entity.value, {}).get("headers", [])
    return tuple(tuple(normalize_header(w)) for w in words)


@cache
def context_keywords(entity: EntityType) -> tuple[str, ...] | None:
    """None — тип не ищется в свободном тексте; () — ищется без ключевого слова."""
    words = _rules()["entities"].get(entity.value, {}).get("context")
    return None if words is None else tuple(w.lower().replace("ё", "е") for w in words)


def _token_match(kw: str, token: str) -> bool:
    return token.startswith(kw) if len(kw) >= 3 else token == kw


def header_hit(header: str, entity: EntityType) -> str | None:
    """Возвращает совпавшее ключевое слово или None."""
    tokens = normalize_header(header)
    for kw in _header_keywords(entity):
        n = len(kw)
        for i in range(len(tokens) - n + 1):
            if all(_token_match(k, t) for k, t in zip(kw, tokens[i : i + n], strict=True)):
                return " ".join(kw)
    return None
