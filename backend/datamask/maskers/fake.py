"""Фейки Faker ru_RU с детерминированным seed = HMAC(секрет, тип, нормализованное значение)."""

from __future__ import annotations

import random
import re
import threading
from collections.abc import Callable

from faker import Faker
from faker.providers.person.ru_RU import Provider as RuNames

from datamask.core.models import CellValue, EntityType
from datamask.core.normalize import digits, normalize, to_text
from datamask.detectors import validators as v
from datamask.maskers.base import MaskContext, MaskSkip, keyed_hash, substitute_digits

E = EntityType
MAX_ATTEMPTS = 50
_local = threading.local()  # Faker не потокобезопасен, задачи идут в фоновых потоках
_FIRST = frozenset(n.lower() for n in (*RuNames.first_names_male, *RuNames.first_names_female))
_FEMALE = frozenset(n.lower() for n in RuNames.first_names_female)
_SHORT = re.compile(r"\S+\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.?")
_SHORT_FIRST = re.compile(r"[А-ЯЁ]\.\s?[А-ЯЁ]\.\s?\S+")
_ORG_FORM = re.compile(r"(ООО|ОАО|ЗАО|ПАО|АО|НКО|АНО|НПО|ИП|ТОО|ГУП|МУП|ФГУП)\s+")


def _faker(seed: int) -> Faker:
    f: Faker | None = getattr(_local, "faker", None)
    if f is None:
        f = _local.faker = Faker("ru_RU")
    f.seed_instance(seed)
    return f


def _checked(rnd: random.Random, prefix_len: int, total: int, ok: Callable[[str], bool]) -> str:
    """Случайные цифры + подобранные контрольные: фейк проходит проверку контрольной суммы."""
    while True:
        p = str(rnd.randint(1, 9)) + "".join(str(rnd.randint(0, 9)) for _ in range(prefix_len - 1))
        tail = total - prefix_len
        for t in range(10**tail):
            cand = p + f"{t:0{tail}d}"
            if ok(cand):
                return cand


def _person(f: Faker, s: str) -> str:
    words = s.split()
    female = any(re.search(r"(вна|ична|кызы)$", w) for w in words) or any(
        w.lower() in _FEMALE for w in words
    )
    if not female and len(words) <= 2 and words:
        female = bool(re.search(r"(ова|ева|ина|ая|ская)$", words[0].lower()))
    g = "female" if female else "male"
    last = getattr(f, f"last_name_{g}")()
    first = getattr(f, f"first_name_{g}")()
    middle = getattr(f, f"middle_name_{g}")()
    if _SHORT.fullmatch(s):
        return f"{last} {first[0]}.{middle[0]}."
    if _SHORT_FIRST.fullmatch(s):
        return f"{first[0]}.{middle[0]}. {last}"
    first_is_name = bool(words) and words[0].lower() in _FIRST
    if len(words) >= 3:
        return f"{first} {middle} {last}" if first_is_name else f"{last} {first} {middle}"
    if len(words) == 2:
        return f"{first} {last}" if first_is_name else f"{last} {first}"
    return str(first if first_is_name else last)


def _generate(entity: EntityType, s: str, f: Faker, rnd: random.Random) -> str:
    d = digits(s)
    match entity:
        case E.PERSON:
            return _person(f, s)
        case E.PHONE:
            if len(d) == 11 and d[0] in "78":
                new = d[0] + "9" + "".join(str(rnd.randint(0, 9)) for _ in range(9))
            elif len(d) == 10:
                new = "9" + "".join(str(rnd.randint(0, 9)) for _ in range(9))
            else:
                raise MaskSkip
            return substitute_digits(s, new)  # та же запись: «8 (912) …» остаётся «8 (9xx) …»
        case E.EMAIL:
            return f"{f.user_name()}{rnd.randint(1, 99)}@{f.free_email_domain()}"
        case E.ADDRESS:
            return str(f.address())
        case E.ORG:
            m = _ORG_FORM.match(s)
            if m and m[1] == "ИП":
                return (
                    f"ИП {f.last_name_male()} {f.first_name_male()[0]}.{f.middle_name_male()[0]}."
                )
            name = f.last_name_male() + rnd.choice(["", " Групп", "-Трейд", "Строй", "Снаб"])
            return f"{m[1] if m else 'ООО'} «{name}»"
        case E.INN_PERSON | E.INN_ORG | E.SNILS | E.CARD:
            total = {E.INN_PERSON: 12, E.INN_ORG: 10, E.SNILS: 11}.get(entity) or (
                len(d) if 13 <= len(d) <= 19 else 16
            )
            prefix = total - (2 if entity in (E.INN_PERSON, E.SNILS) else 1)
            ok = {E.INN_PERSON: v.inn_person_ok, E.INN_ORG: v.inn_org_ok, E.SNILS: v.snils_ok}.get(
                entity, v.luhn_ok
            )
            new = _checked(rnd, prefix, total, ok)
            return substitute_digits(s, new) if len(d) == total else new
    raise MaskSkip


class FakeMasker:
    name = "fake"
    reversible = True
    supports = frozenset(
        {E.PERSON, E.PHONE, E.EMAIL, E.ADDRESS, E.ORG, E.INN_PERSON, E.INN_ORG, E.SNILS, E.CARD}
    )

    def mask(self, value: CellValue, entity: EntityType, ctx: MaskContext) -> CellValue:
        s = to_text(value)
        key = (entity, "fake", normalize(entity, value))
        result = ctx.store.get(key)
        if result is None:
            originals = ctx.originals.get(entity, set())
            for attempt in range(MAX_ATTEMPTS):
                seed = int.from_bytes(
                    keyed_hash(ctx.store.secret, "fake", entity.value, key[2], str(attempt))[:8]
                )
                cand = _generate(entity, s, _faker(seed), random.Random(seed))  # noqa: S311
                # Фейк не должен совпасть ни с исходником, ни с другим фейком: иначе
                # размаскировка станет неоднозначной.
                if normalize(entity, cand) not in originals and ctx.store.owner(cand) is None:
                    result = cand
                    break
            else:
                raise MaskSkip
            ctx.store.add(key, s, result, self.name)
        if isinstance(value, int) and result.isdigit():
            return int(result)
        return result
