"""A3: контрольные суммы; распознаватели, заголовки, свободный текст, свой словарь."""

import random

import pytest
from faker import Faker
from hypothesis import given
from hypothesis import strategies as st

from datamask.core.models import EntityType as E
from datamask.core.models import Span
from datamask.detectors import validators as v
from datamask.detectors.base import DetectContext, find_spans, resolve_overlaps
from datamask.detectors.headers import header_hit
from datamask.detectors.regex_ru import (
    DETECTORS,
    CustomTermsDetector,
    address_score,
    digits,
    person_score,
)

DET = {d.entity: d for d in DETECTORS}
CTX = DetectContext()


def prefix(n: int):
    return st.text(alphabet="0123456789", min_size=n, max_size=n)


# --- A3: на любой префикс ровно одна верная контрольная часть, т.е. случайная строка
# проходит проверку с вероятностью ровно 1/10 (или 1/100 для двух контрольных цифр).


@given(prefix(9))
def test_inn_org_one_check_digit(p) -> None:
    assert sum(v.inn_org_ok(p + str(d)) for d in range(10)) == 1


@given(prefix(10))
def test_inn_person_one_check_pair(p) -> None:
    assert sum(v.inn_person_ok(p + f"{d:02d}") for d in range(100)) == 1


@given(prefix(12))
def test_ogrn_one_check_digit(p) -> None:
    assert sum(v.ogrn_ok(p + str(d)) for d in range(10)) == 1


@given(prefix(14))
def test_ogrnip_one_check_digit(p) -> None:
    assert sum(v.ogrn_ok(p + str(d)) for d in range(10)) == 1


@given(st.integers(12, 18).flatmap(prefix))
def test_luhn_one_check_digit(p) -> None:
    assert sum(v.luhn_ok(p + str(d)) for d in range(10)) == 1


@given(st.integers(1_001_999, 999_999_999))
def test_snils_one_check_number(n) -> None:
    assert sum(v.snils_ok(f"{n:09d}{c:02d}") for c in range(100)) == 1


@pytest.mark.parametrize(
    ("entity", "length", "expected"),
    [
        (E.INN_ORG, 10, 0.1),
        (E.INN_PERSON, 12, 0.01),
        (E.SNILS, 11, 0.01),
        (E.OGRN, 13, 0.1),
        (E.CARD, 16, 0.1),
    ],
)
def test_random_digits_rate(entity, length, expected) -> None:
    rnd = random.Random(entity.value)
    n = 20_000
    hits = sum(
        DET[entity].match_value("".join(rnd.choice("0123456789") for _ in range(length))) >= 0.5
        for _ in range(n)
    )
    assert hits / n <= expected * 1.3


FAKE = Faker("ru_RU")
FAKE.seed_instance(1)


@pytest.mark.parametrize(
    ("entity", "make"),
    [
        (E.INN_PERSON, FAKE.individuals_inn),
        (E.INN_ORG, FAKE.businesses_inn),
        (E.OGRN, FAKE.businesses_ogrn),
        (E.OGRN, FAKE.individuals_ogrn),
        (E.SNILS, FAKE.snils),
        (E.CARD, FAKE.credit_card_number),
    ],
)
def test_valid_numbers_found_and_corrupted_rejected(entity, make) -> None:
    for _ in range(100):
        good = make()
        assert DET[entity].match_value(good) == 1.0, good
        d = digits(good)
        bad = d[:-1] + str((int(d[-1]) + 1) % 10)
        assert DET[entity].match_value(bad) == 0.0, bad


def test_formatted_numbers() -> None:
    assert DET[E.SNILS].match_value(f"{FAKE.snils()[:3]}-") == 0.0
    s = FAKE.snils()
    assert DET[E.SNILS].match_value(f"{s[:3]}-{s[3:6]}-{s[6:9]} {s[9:]}") == 1.0
    c = FAKE.credit_card_number(card_type="mastercard")
    assert DET[E.CARD].match_value(f"{c[:4]} {c[4:8]} {c[8:12]} {c[12:]}") == 1.0


@pytest.mark.parametrize(
    "phone",
    ["8 (912) 123-45-67", "+7 912 1234567", "89121234567", "+7(912)123-45-67", "8-912-123-45-67"],
)
def test_phone_formats(phone) -> None:
    assert DET[E.PHONE].match_value(phone) == 1.0


@pytest.mark.parametrize("bad", ["12345", "+1 912 123 45 67", "7912123456", "8912123456789"])
def test_not_phone(bad) -> None:
    assert DET[E.PHONE].match_value(bad) == 0.0


def test_email_and_ip() -> None:
    assert DET[E.EMAIL].match_value("иван.петров@почта.рф") == 1.0
    assert DET[E.EMAIL].match_value("i.petrov+crm@mail.ru") == 1.0
    assert DET[E.EMAIL].match_value("не почта@") == 0.0
    assert DET[E.IP].match_value("192.168.1.10") == 1.0
    assert DET[E.IP].match_value("256.1.1.1") == 0.0
    assert DET[E.IP].match_value("1.2.3") == 0.0


def test_person_and_address_scores() -> None:
    assert person_score("Иванов Иван Иванович") >= 0.9
    assert person_score("Петрова Анна Сергеевна") >= 0.9
    assert person_score("Иванов И.И.") >= 0.9
    assert person_score("И.И. Иванов") >= 0.9
    assert person_score("Иван") == 0.5
    assert person_score("Москва") < 0.5
    assert person_score("Ноутбук") < 0.5
    assert person_score("в работе") == 0.0
    assert address_score("г. Москва, ул. Ленина, д. 5, кв. 12") >= 0.9
    assert address_score("123456, Казань, пр-т Победы") >= 0.9
    assert address_score("Москва") == 0.0


def test_header_hits() -> None:
    assert header_hit("Тел.", E.PHONE)
    assert header_hit("Моб. телефон", E.PHONE)
    assert header_hit("Д.р.", E.BIRTH_DATE)
    assert header_hit("Дата рождения", E.BIRTH_DATE)
    assert header_hit("Расчётный счёт", E.ACCOUNT)
    assert header_hit("Р/с", E.ACCOUNT)
    assert header_hit("Серия и номер паспорта", E.PASSPORT)
    assert header_hit("Full name", E.PERSON)
    assert not header_hit("Дата регистрации", E.BIRTH_DATE)
    assert not header_hit("Дата заказа", E.BIRTH_DATE)
    assert not header_hit("Наименование товара", E.PERSON)
    assert not header_hit("Количество", E.AMOUNT)


def test_free_text_strong() -> None:
    text = "Звоните +7 912 123-45-67 или пишите на ivan@mail.ru. ИНН 500100732259."
    spans = find_spans(text, DETECTORS, CTX)
    assert [(s.entity, text[s.start : s.end]) for s in spans][:2] == [
        (E.PHONE, "+7 912 123-45-67"),
        (E.EMAIL, "ivan@mail.ru"),
    ]


def test_free_text_weak_needs_keyword() -> None:
    def found(text: str) -> list[E]:
        return [s.entity for s in find_spans(text, DETECTORS, CTX)]

    assert found("паспорт 4506 123456 выдан") == [E.PASSPORT]
    assert found("заказ 4506 123456 отгружен") == []
    assert found("р/с 40702810900000012345 в банке") == [E.ACCOUNT]
    assert found("номер 40702810900000012345") == []
    assert found("Иванов, д.р. 14.03.1991") == [E.BIRTH_DATE]
    assert found("отгрузка 14.03.1991") == []
    assert found("договор с ООО «Ромашка» продлён") == [E.ORG]
    # имена и адреса в свободном тексте в v1 не ищутся (честное ограничение)
    assert found("менеджер Иванов Иван Иванович, г. Москва, ул. Ленина, д. 5") == []


def test_keyword_window() -> None:
    far = "паспорт" + " " * 40 + "4506 123456"
    assert find_spans(far, DETECTORS, CTX) == []


def test_resolve_overlaps() -> None:
    a = Span(0, 10, E.PHONE, 0.9, "a")
    b = Span(5, 15, E.SNILS, 0.99, "b")
    c = Span(20, 25, E.EMAIL, 0.5, "c")
    d = Span(20, 30, E.EMAIL, 0.5, "d")
    assert resolve_overlaps([a, b, c, d]) == [b, d]


def test_custom_terms() -> None:
    det = CustomTermsDetector(["Ромашка", "Проект  Альфа", "Ёлка", " "])

    def found(text: str) -> list[str]:
        return [text[s.start : s.end] for s in det.detect(text, CTX)]

    assert found("ООО РОМАШКА и ромашка") == ["РОМАШКА", "ромашка"]
    assert found("по проекту: Проект альфа, проект   АЛЬФА") == ["Проект альфа", "проект   АЛЬФА"]
    assert found("ёлка и Елка") == ["ёлка", "Елка"]
    assert found("Ромашкина и Ромашка-2") == ["Ромашка"]
    assert det.match_value(" ромашка ") == 1.0
    assert CustomTermsDetector([]).detect("Ромашка", CTX) == []
