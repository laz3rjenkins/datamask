"""Реестр способов маскирования. Новый способ = новый класс здесь."""

from datamask.core.models import EntityType
from datamask.maskers.base import Masker
from datamask.maskers.dates import DateGeneralizeMasker, DateShiftMasker
from datamask.maskers.fake import FakeMasker
from datamask.maskers.hash import HashMasker
from datamask.maskers.label import DeleteMasker, LabelMasker
from datamask.maskers.numbers import NoiseMasker, ScaleMasker
from datamask.maskers.partial import PartialMasker
from datamask.maskers.pseudonym import PseudonymMasker

MASKERS: dict[str, Masker] = {
    m.name: m
    for m in (
        PseudonymMasker(),
        FakeMasker(),
        HashMasker(),
        LabelMasker(),
        PartialMasker(),
        DeleteMasker(),
        DateShiftMasker(),
        DateGeneralizeMasker(),
        ScaleMasker(),
        NoiseMasker(),
    )
}
METHOD_LABELS = {
    "pseudonym": "Псевдоним",
    "fake": "Фейк",
    "hash": "Хеш",
    "label": "Метка",
    "partial": "Частичное скрытие",
    "delete": "Удаление",
    "date_shift": "Сдвиг дат",
    "date_generalize": "Обобщение дат",
    "scale": "Масштабирование",
    "noise": "Шум",
}
# В свободном тексте способ применяется к каждому найденному фрагменту.
FREE_TEXT_METHODS = frozenset({"pseudonym", "hash", "label", "delete"})


def supported(entity: EntityType, method: str) -> bool:
    if entity == EntityType.FREE_TEXT:
        return method in FREE_TEXT_METHODS
    m = MASKERS.get(method)
    return m is not None and entity in m.supports


def reversible(method: str) -> bool:
    return method in MASKERS and MASKERS[method].reversible
