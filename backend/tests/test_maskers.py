"""A2 (нормализация), A10 (фейки), A16 (шифрование), поведение способов маскирования."""

import re
from datetime import date, datetime

import pytest

from datamask.core.models import EntityType as E
from datamask.core.normalize import digits, normalize
from datamask.detectors import validators as v
from datamask.mapping.crypto import MappingError
from datamask.mapping.store import MappingStore
from datamask.maskers import MASKERS, supported
from datamask.maskers.base import MaskContext, MaskSkip

SECRET = b"s" * 32


def ctx(store=None, **params):
    return MaskContext(store or MappingStore(SECRET), params, "Лист!A", {"header": "x"})


def mask(method, value, entity, c=None, **params):
    return MASKERS[method].mask(value, entity, c or ctx(**params))


# ---- A2 ----


def test_a2_phone_forms_one_pseudonym() -> None:
    c = ctx()
    tokens = {
        mask("pseudonym", p, E.PHONE, c)
        for p in ["8 (912) 123-45-67", "+7 912 1234567", "89121234567"]
    }
    assert tokens == {"Телефон_0001"}
    assert normalize(E.PHONE, "8 (912) 123-45-67") == "+79121234567"


def test_a2_names_case_spaces_yo() -> None:
    c = ctx()
    assert mask("pseudonym", "Иванов Иван", E.PERSON, c) == mask(
        "pseudonym", "иванов  иван", E.PERSON, c
    )
    assert mask("pseudonym", "Королёв Пётр", E.PERSON, c) == mask(
        "pseudonym", "КОРОЛЕВ петр ", E.PERSON, c
    )


def test_a2_other_normalizations() -> None:
    assert normalize(E.EMAIL, " Ivan@Mail.RU ") == "ivan@mail.ru"
    assert normalize(E.SNILS, "123-456-789 01") == "12345678901"
    assert normalize(E.CARD, "4111 1111 1111 1111") == "4111111111111111"
    assert normalize(E.INN_PERSON, 500100732259) == "500100732259"
    assert normalize(E.BIRTH_DATE, datetime(1991, 3, 14)) == "1991-03-14"


# ---- псевдоним, хеш, метка, удаление ----


def test_pseudonym_numbering_and_prefix() -> None:
    c = ctx()
    assert mask("pseudonym", "А", E.PERSON, c) == "Персона_0001"
    assert mask("pseudonym", "Б", E.PERSON, c) == "Персона_0002"
    assert mask("pseudonym", "А", E.PERSON, c) == "Персона_0001"
    c2 = ctx(c.store, prefix="Клиент")
    assert mask("pseudonym", "В", E.PERSON, c2) == "Клиент_0001"
    assert mask("pseudonym", "А", E.PERSON, c2) == "Персона_0001"  # согласованность важнее префикса
    assert mask("pseudonym", "Ромашка", E.CUSTOM, c) == "Термин_0001"


def test_hash_is_keyed_and_stable() -> None:
    a = mask("hash", "+7 912 123-45-67", E.PHONE)
    assert re.fullmatch(r"Телефон_[0-9a-f]{10}", str(a))
    assert a == mask("hash", "89121234567", E.PHONE)
    other = MASKERS["hash"].mask("89121234567", E.PHONE, ctx(MappingStore(b"x" * 32)))
    assert other != a  # без секрета перебором не восстановить
    assert re.fullmatch(r"ФИО_[0-9a-f]{10}", str(mask("hash", "Иванов", E.PERSON)))


def test_label_and_delete() -> None:
    assert mask("label", "Иванов", E.PERSON) == "[ФИО]"
    assert mask("delete", "Иванов", E.PERSON) is None


# ---- частичное скрытие ----


@pytest.mark.parametrize(
    ("value", "entity", "expected"),
    [
        ("+7 912 123-45-67", E.PHONE, "+7 *** ***-45-67"),
        ("89121234567", E.PHONE, "8******4567"),
        ("ivan.petrov@mail.ru", E.EMAIL, "i***@m***.ru"),
        ("4111 1111 1111 1234", E.CARD, "**** **** **** 1234"),
        ("123-456-789 01", E.SNILS, "***-***-*89 01"),
        (500100732259, E.INN_PERSON, "********2259"),
    ],
)
def test_partial(value, entity, expected) -> None:
    assert mask("partial", value, entity) == expected


def test_partial_skips_unmatched() -> None:
    with pytest.raises(MaskSkip):
        mask("partial", "нет", E.PHONE)
    with pytest.raises(MaskSkip):
        mask("partial", "не почта", E.EMAIL)


# ---- даты и числа: тип сохраняется (A7) ----


def test_date_shift_keeps_type_and_interval() -> None:
    c = ctx()
    a = mask("date_shift", datetime(1991, 3, 14), E.BIRTH_DATE, c)
    b = mask("date_shift", datetime(1991, 3, 24), E.BIRTH_DATE, c)
    assert isinstance(a, datetime) and (b - a).days == 10
    shift = (a - datetime(1991, 3, 14)).days
    assert shift != 0 and -365 <= shift <= 365
    s = mask("date_shift", "14.03.1991", E.BIRTH_DATE, c)
    assert s == a.strftime("%d.%m.%Y")  # строка — в том же формате
    assert isinstance(mask("date_shift", date(2000, 1, 1), E.BIRTH_DATE, c), date)
    with pytest.raises(MaskSkip):
        mask("date_shift", "вчера", E.BIRTH_DATE, c)


def test_date_shift_scope_file_vs_column() -> None:
    store = MappingStore(SECRET)
    a = MaskContext(store, {"scope": "file"}, "Лист!A")
    b = MaskContext(store, {"scope": "file"}, "Лист!B")
    d = datetime(2000, 1, 1)
    assert MASKERS["date_shift"].mask(d, E.BIRTH_DATE, a) == MASKERS["date_shift"].mask(
        d, E.BIRTH_DATE, b
    )
    assert list(store.date_shifts) == ["*"]


def test_date_generalize() -> None:
    assert mask("date_generalize", datetime(1991, 3, 14), E.BIRTH_DATE) == datetime(1991, 3, 1)
    assert mask("date_generalize", datetime(1991, 3, 14), E.BIRTH_DATE, level="year") == 1991
    assert mask("date_generalize", "14.03.1991", E.BIRTH_DATE, level="year") == "1991"


def test_scale_keeps_types_and_proportions() -> None:
    c = ctx()
    a = mask("scale", 1000.0, E.AMOUNT, c)
    b = mask("scale", 2000.0, E.AMOUNT, c)
    assert isinstance(a, float) and abs(b / a - 2) < 0.01
    assert isinstance(mask("scale", 1000, E.AMOUNT, c), int)
    s = mask("scale", "1 000,50", E.AMOUNT, c)
    assert re.fullmatch(r"\d+,\d{2}", str(s))
    factor = c.store.scale_factors["Лист!A"]["factor"]
    assert 0.5 <= factor <= 2.0


def test_noise_bounded() -> None:
    for _ in range(50):
        x = mask("noise", 1000.0, E.AMOUNT, percent=10)
        assert isinstance(x, float) and 900 <= x <= 1100


def test_supported_pairs() -> None:
    assert supported(E.PHONE, "partial") and not supported(E.EMAIL, "date_shift")
    assert supported(E.FREE_TEXT, "pseudonym") and not supported(E.FREE_TEXT, "fake")
    assert not supported(E.OGRN, "fake") and not supported(E.PERSON, "nope")


# ---- A10: фейки ----

FAKE_CASES = [
    (
        E.PERSON,
        ["Иванов Иван Иванович", "Петрова Анна Сергеевна", "Сидоров П.К.", "Ольга Смирнова"],
    ),
    (E.PHONE, ["8 (912) 123-45-67", "+79121234568", "8-912-123-45-69"]),
    (E.EMAIL, ["ivan@mail.ru", "anna@yandex.ru"]),
    (E.INN_PERSON, ["500100732259", "773370857141"]),
    (E.INN_ORG, ["7707083893", "5001007329"]),
    (E.SNILS, ["112-233-445 95", "08765430300"]),
    (E.CARD, ["4111 1111 1111 1111", "5500000000000004"]),
    (E.ORG, ["ООО «Ромашка»", "ИП Иванов И.И."]),
    (E.ADDRESS, ["г. Москва, ул. Ленина, д. 5"]),
]


@pytest.mark.parametrize(("entity", "values"), FAKE_CASES)
def test_a10_fakes(entity, values) -> None:
    originals = {normalize(entity, x) for x in values}
    store = MappingStore(SECRET)
    c = MaskContext(store, originals={entity: originals})
    fakes = [MASKERS["fake"].mask(x, entity, c) for x in values]
    assert len(set(fakes)) == len(fakes)
    assert not {normalize(entity, f) for f in fakes} & originals
    # детерминированность: тот же секрет (проект) → тот же фейк
    again = MaskContext(MappingStore(SECRET), originals={entity: originals})
    assert [MASKERS["fake"].mask(x, entity, again) for x in values] == fakes
    check = {
        E.INN_PERSON: v.inn_person_ok,
        E.INN_ORG: v.inn_org_ok,
        E.SNILS: v.snils_ok,
        E.CARD: v.luhn_ok,
    }
    if entity in check:
        assert all(check[entity](digits(str(f))) for f in fakes)


def test_fake_keeps_structure() -> None:
    c = ctx()
    phone = mask("fake", "8 (912) 123-45-67", E.PHONE, c)
    assert re.fullmatch(r"8 \(9\d\d\) \d{3}-\d\d-\d\d", str(phone))
    assert re.fullmatch(
        r"[А-ЯЁ][а-яё-]+ [А-ЯЁ]\.[А-ЯЁ]\.", str(mask("fake", "Иванов И.И.", E.PERSON, c))
    )
    assert len(str(mask("fake", "Иванов Иван Иванович", E.PERSON, c)).split()) == 3
    assert (
        str(mask("fake", "Петрова Анна Сергеевна", E.PERSON, c)).split()[2].endswith(("вна", "чна"))
    )
    assert str(mask("fake", "ООО «Ромашка»", E.ORG, c)).startswith("ООО «")
    assert re.fullmatch(r"\d{3}-\d{3}-\d{3} \d{2}", str(mask("fake", "112-233-445 95", E.SNILS, c)))
    assert isinstance(mask("fake", 500100732259, E.INN_PERSON, c), int)


def test_fake_avoids_collision_with_original(monkeypatch) -> None:
    store = MappingStore(SECRET)
    first = MASKERS["fake"].mask("Иванов Иван Иванович", E.PERSON, MaskContext(store))
    # второе значение совпадает с фейком первого → его фейк должен быть другим
    c = MaskContext(MappingStore(SECRET), originals={E.PERSON: {normalize(E.PERSON, first)}})
    assert MASKERS["fake"].mask("Иванов Иван Иванович", E.PERSON, c) != first


# ---- A16: таблица соответствий ----


def test_a16_roundtrip_and_errors() -> None:
    store = MappingStore(SECRET)
    c = ctx(store)
    mask("pseudonym", "Иванов Иван Иванович", E.PERSON, c)
    mask("date_shift", datetime(1991, 3, 14), E.BIRTH_DATE, c)
    blob = store.encrypt("правильный-пароль")
    assert blob.startswith(b"DMMAP1")
    assert "Иванов".encode() not in blob and b"Ivanov" not in blob

    loaded = MappingStore.decrypt(blob, "правильный-пароль")
    assert [(e.original, e.masked) for e in loaded.entries] == [
        ("Иванов Иван Иванович", "Персона_0001")
    ]
    assert loaded.date_shifts == store.date_shifts
    assert loaded.next_number("Персона") == 2  # нумерация продолжается

    with pytest.raises(MappingError, match="Неверный пароль или файл повреждён"):
        MappingStore.decrypt(blob, "неправильный-пароль")
    for pos in (3, 10, 30, len(blob) - 1):
        broken = bytearray(blob)
        broken[pos] ^= 1
        with pytest.raises(MappingError, match="Неверный пароль или файл повреждён"):
            MappingStore.decrypt(bytes(broken), "правильный-пароль")
    with pytest.raises(MappingError):
        MappingStore.decrypt(b"garbage", "правильный-пароль")
    with pytest.raises(MappingError, match="не короче"):
        store.encrypt("short")
