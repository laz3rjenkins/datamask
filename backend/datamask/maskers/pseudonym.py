from __future__ import annotations

from datamask.core.models import CellValue, EntityType
from datamask.core.normalize import normalize, to_text
from datamask.maskers.base import TEXT, MaskContext

E = EntityType
PREFIXES: dict[EntityType, str] = {
    E.PERSON: "Персона",
    E.PHONE: "Телефон",
    E.EMAIL: "Email",
    E.INN_PERSON: "ИНН",
    E.INN_ORG: "ИНН",
    E.SNILS: "СНИЛС",
    E.CARD: "Карта",
    E.ACCOUNT: "Счёт",
    E.PASSPORT: "Паспорт",
    E.ADDRESS: "Адрес",
    E.ORG: "Организация",
    E.OGRN: "ОГРН",
    E.IP: "IP",
    E.CUSTOM: "Термин",
    E.BIRTH_DATE: "Дата",  # только для дат, найденных в свободном тексте
}


class PseudonymMasker:
    name = "pseudonym"
    reversible = True
    supports = TEXT

    def mask(self, value: CellValue, entity: EntityType, ctx: MaskContext) -> CellValue:
        # Ключ без префикса: один человек в колонках «Менеджер» и «Клиент» — один псевдоним.
        # Префикс берётся из колонки, где значение встретилось впервые.
        key = (entity, "pseudonym", normalize(entity, value))
        token = ctx.store.get(key)
        if token is None:
            prefix = str(ctx.params.get("prefix") or PREFIXES[entity])
            token = f"{prefix}_{ctx.store.next_number(prefix):04d}"
            ctx.store.add(key, to_text(value), token, self.name)
        return token
