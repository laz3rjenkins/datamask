"""Общие типы ядра. Ничего не знают о форматах файлов и HTTP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, Field


class UserError(Exception):
    """Ошибка, текст которой безопасно показать пользователю: без данных из файла."""


CellValue = str | int | float | bool | datetime | date | time | None
CellKind = Literal["empty", "string", "number", "bool", "date", "formula", "error"]


def kind_of(value: CellValue) -> CellKind:
    if value is None or value == "":
        return "empty"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, datetime | date | time):
        return "date"
    return "string"


class CellRef(NamedTuple):
    """Адрес и значение ячейки. NamedTuple, а не dataclass: создаётся на каждую ячейку
    файла (десятки миллионов), так втрое дешевле."""

    sheet: str
    row: int  # с 1
    col: int  # с 1
    value: CellValue
    kind: CellKind


@dataclass(frozen=True)
class Risk:
    code: str  # hidden_sheet, hidden_columns, comments, pivot_cache, images, external_links
    message: str  # по-русски; имена листов можно, значения ячеек нельзя
    sheet: str | None = None
    count: int = 1


class EntityType(StrEnum):
    PERSON = "PERSON"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    ADDRESS = "ADDRESS"
    BIRTH_DATE = "BIRTH_DATE"
    PASSPORT = "PASSPORT"
    SNILS = "SNILS"
    INN_PERSON = "INN_PERSON"
    IP = "IP"
    CARD = "CARD"
    ACCOUNT = "ACCOUNT"
    ORG = "ORG"
    INN_ORG = "INN_ORG"
    OGRN = "OGRN"
    AMOUNT = "AMOUNT"
    CUSTOM = "CUSTOM"
    FREE_TEXT = "FREE_TEXT"


class Category(StrEnum):
    PERSONAL = "personal"
    FINANCIAL = "financial"
    COMMERCIAL = "commercial"


E = EntityType
ENTITY_CATEGORY: dict[EntityType, Category] = {
    **dict.fromkeys(
        (
            E.PERSON,
            E.PHONE,
            E.EMAIL,
            E.ADDRESS,
            E.BIRTH_DATE,
            E.PASSPORT,
            E.SNILS,
            E.INN_PERSON,
            E.IP,
        ),
        Category.PERSONAL,
    ),
    **dict.fromkeys((E.CARD, E.ACCOUNT), Category.FINANCIAL),
    **dict.fromkeys((E.ORG, E.INN_ORG, E.OGRN, E.AMOUNT, E.CUSTOM), Category.COMMERCIAL),
}

ENTITY_LABELS: dict[EntityType, str] = {
    E.PERSON: "ФИО",
    E.PHONE: "Телефон",
    E.EMAIL: "Email",
    E.ADDRESS: "Адрес",
    E.BIRTH_DATE: "Дата рождения",
    E.PASSPORT: "Паспорт",
    E.SNILS: "СНИЛС",
    E.INN_PERSON: "ИНН физлица",
    E.IP: "IP-адрес",
    E.CARD: "Номер карты",
    E.ACCOUNT: "Расчётный счёт",
    E.ORG: "Организация",
    E.INN_ORG: "ИНН юрлица",
    E.OGRN: "ОГРН",
    E.AMOUNT: "Сумма",
    E.CUSTOM: "Свой словарь",
    E.FREE_TEXT: "Свободный текст",
}


@dataclass(frozen=True, slots=True)
class Span:
    start: int  # позиции символов в тексте
    end: int
    entity: EntityType
    score: float  # 0..1
    detector: str  # какой распознаватель нашёл


@dataclass(frozen=True)
class TextFragment:
    """Текст вне ячеек: имя листа, именованный диапазон, примечание, его автор."""

    kind: str  # sheet_name, defined_name, comment, comment_author
    text: str
    sheet: str | None = None
    ref: str | None = None  # адрес ячейки для примечания


# ---- конфигурация маскирования (SPEC §10) ----


class Categories(BaseModel):
    personal: bool = True
    financial: bool = True
    commercial: bool = False

    def enabled(self) -> list[Category]:
        return [Category(k) for k, on in self.model_dump().items() if on]


class ColumnConfig(BaseModel):
    entity: EntityType
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class SheetConfig(BaseModel):
    header_row: int = Field(1, ge=1)
    columns: dict[str, ColumnConfig] = Field(default_factory=dict)  # буква (XLSX) или номер (CSV)
    scan_above_header: bool = True


class SanitizePolicy(BaseModel):
    metadata: Literal[True] = True  # очищается всегда
    comments: Literal["remove", "keep"] = (
        "remove"  # keep — оставить и проверить как свободный текст
    )
    hidden_sheets: Literal["keep", "remove"] = "keep"
    pivot_cache: Literal["remove"] = "remove"
    images: Literal["keep", "remove"] = "keep"


class MaskConfig(BaseModel):
    categories: Categories = Field(default_factory=Categories)
    consistency_scope: Literal["file", "project"] = "file"
    project_id: str | None = None
    sheets: dict[str, SheetConfig] = Field(default_factory=dict)
    custom_terms: list[str] = Field(default_factory=list)
    sanitize: SanitizePolicy = Field(default_factory=SanitizePolicy)
    save_mapping: bool = True
