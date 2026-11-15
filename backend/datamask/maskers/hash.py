from __future__ import annotations

from datamask.core.models import CellValue, EntityType
from datamask.core.normalize import normalize, to_text
from datamask.maskers.base import TEXT, MaskContext, keyed_hash
from datamask.maskers.pseudonym import PREFIXES

E = EntityType
PREFIXES_HASH = {**PREFIXES, E.PERSON: "ФИО"}


class HashMasker:
    """HMAC-SHA256 с секретом: без секрета телефоны и ИНН перебираются за минуты."""

    name = "hash"
    reversible = True  # через таблицу соответствий
    supports = TEXT

    def mask(self, value: CellValue, entity: EntityType, ctx: MaskContext) -> CellValue:
        key = (entity, "hash", normalize(entity, value))
        token = ctx.store.get(key)
        if token is None:
            digest = keyed_hash(ctx.store.secret, "hash", entity.value, key[2]).hex()
            n = 10
            while True:  # совпадение 40 бит у разных значений: удлиняем
                token = f"{PREFIXES_HASH[entity]}_{digest[:n]}"
                if ctx.store.owner(token) in (None, key):
                    break
                n += 2
            ctx.store.add(key, to_text(value), token, self.name)
        return token
