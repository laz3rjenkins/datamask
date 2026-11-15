"""Интерфейс маскировщика (SPEC §9)."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any, Protocol

from datamask.core.models import CellValue, EntityType
from datamask.mapping.store import MappingStore

E = EntityType
ALL = frozenset(EntityType) - {E.FREE_TEXT}
TEXT = ALL - {E.BIRTH_DATE, E.AMOUNT}  # «все текстовые и идентификаторы»


class MaskSkip(Exception):
    """Значение не подходит способу (дата не разбирается, нет цифр). Остаётся как было."""


@dataclass
class MaskContext:
    store: MappingStore
    params: dict[str, Any] = field(default_factory=dict)
    scope: str = "*"  # «Лист!B» — для сдвига дат и масштаба по колонке
    info: dict[str, str] = field(
        default_factory=dict
    )  # лист, колонка, заголовок — для размаскировки
    originals: dict[EntityType, set[str]] = field(default_factory=dict)  # для фейков

    def column_scope(self) -> str:
        return "*" if self.params.get("scope") == "file" else self.scope


class Masker(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def reversible(self) -> bool: ...
    @property
    def supports(self) -> frozenset[EntityType]: ...

    def mask(self, value: CellValue, entity: EntityType, ctx: MaskContext) -> CellValue: ...


def keyed_hash(secret: bytes, *parts: str) -> bytes:
    return hmac.new(secret, "\x1f".join(parts).encode(), hashlib.sha256).digest()


def substitute_digits(template: str, new_digits: str) -> str:
    """Подставляет цифры по порядку на места цифр шаблона: формат записи сохраняется."""
    it = iter(new_digits)
    return "".join(next(it) if ch.isdigit() else ch for ch in template)
