"""A8 (круговая проверка обратимых способов) и A9 (размаскировка HTML и JSON)."""

import json
from datetime import datetime

import pytest
from mask_helpers import SECRET, col, run
from openpyxl import load_workbook

from datamask.core.models import EntityType
from datamask.formats.base import OpenOptions
from datamask.formats.csv import CsvAdapter
from datamask.mapping.store import MappingStore
from datamask.mapping.unmask import Unmasker
from datamask.unmasking import unmask_file

E = EntityType
PASSWORD = "пароль-для-теста"

XLSX_CONFIG = {
    "categories": {"personal": True, "financial": True, "commercial": True},
    "sheets": {
        "Клиенты": {
            "header_row": 3,
            "columns": {
                "B": col("PERSON", prefix="Клиент"),
                "C": col("PHONE", "fake"),
                "E": col("INN_PERSON", "fake"),
                "F": col("SNILS", "hash"),
                "G": col("BIRTH_DATE", "date_shift"),
                "I": col("ADDRESS"),
                "K": col("FREE_TEXT"),
            },
        },
        "Продажи": {
            "header_row": 1,
            "columns": {
                "B": col("PERSON", "fake"),
                "C": col("PERSON"),
                "D": col("AMOUNT", "scale"),
            },
        },
        "Архив": {
            "header_row": 1,
            "columns": {
                "A": col("PERSON"),
                "B": col("PHONE", "fake"),
                "C": col("BIRTH_DATE", "date_shift", scope="file"),
            },
        },
    },
}


def reload(store: MappingStore) -> MappingStore:
    """Через настоящий .dmmap: проверяем и сериализацию."""
    return MappingStore.decrypt(store.encrypt(PASSWORD), PASSWORD)


def values(path, sheet):
    return {
        (c.row, c.column): c.value for row in load_workbook(path)[sheet].iter_rows() for c in row
    }


def test_a8_xlsx_roundtrip(fixtures, tmp_path) -> None:
    src = fixtures / "clients.xlsx"
    masked, restored = tmp_path / "m.xlsx", tmp_path / "r.xlsx"
    _, store = run(src, masked, XLSX_CONFIG)
    report = unmask_file(masked, restored, reload(store))

    for sheet in ("Клиенты", "Продажи", "Архив"):
        before, after, mid = values(src, sheet), values(restored, sheet), values(masked, sheet)
        assert before != mid, sheet  # действительно маскировалось
        for pos, v in before.items():
            got = after.get(pos)
            if sheet == "Продажи" and pos[1] == 4 and pos[0] > 1:  # масштаб: до округления
                assert got == pytest.approx(v, abs=max(1, abs(v) * 0.01)), pos
            else:
                assert got == v, (sheet, pos)
    assert report["dates_restored"] > 0 and report["numbers_restored"] > 0
    assert report["unknown_tokens"] == 0 and report["missing_columns"] == []


def test_a8_csv_roundtrip(fixtures, tmp_path) -> None:
    src = fixtures / "clients_cp1251.csv"
    masked, restored = tmp_path / "m.csv", tmp_path / "r.csv"
    config = {
        "sheets": {
            "CSV": {
                "header_row": 1,
                "columns": {
                    "2": col("PERSON", "fake"),
                    "3": col("PHONE"),
                    "4": col("EMAIL", "hash"),
                    "5": col("BIRTH_DATE", "date_shift"),
                    "6": col("ADDRESS", "fake"),
                    "7": col("FREE_TEXT"),
                },
            }
        }
    }
    _, store = run(src, masked, config)
    report = unmask_file(masked, restored, reload(store))
    assert masked.read_bytes() != src.read_bytes()
    assert restored.read_bytes() == src.read_bytes()  # байт в байт: кодировка, «;», CRLF
    assert report["dates_restored"] > 0


def test_restore_by_header_when_column_moved(fixtures, tmp_path) -> None:
    """Даты восстанавливаются по заголовку, даже если колонку переставили."""
    src = fixtures / "clients_utf8.csv"
    masked, moved, restored = tmp_path / "m.csv", tmp_path / "mv.csv", tmp_path / "r.csv"
    _, store = run(
        src, masked, {"sheets": {"CSV": {"columns": {"5": col("BIRTH_DATE", "date_shift")}}}}
    )
    lines = masked.read_text("utf-8-sig").splitlines()
    rows = [line.split(",")[:5] for line in lines]
    moved.write_text("\n".join(",".join([r[4], *r[:4]]) for r in rows) + "\n", "utf-8")
    report = unmask_file(moved, restored, reload(store))
    adapter = CsvAdapter()
    orig = {
        c.row: c.value
        for c in adapter.iter_cells(adapter.open(src, OpenOptions()), "CSV")
        if c.col == 5
    }
    back = {
        c.row: c.value
        for c in adapter.iter_cells(adapter.open(restored, OpenOptions()), "CSV")
        if c.col == 1
    }
    assert back == orig and report["dates_restored"] == len(orig) - 1


def a9_store() -> MappingStore:
    s = MappingStore(SECRET)
    s.add((E.PERSON, "pseudonym", "иванов иван"), "Иванов Иван", "Персона_0017", "pseudonym")
    s.add((E.PERSON, "fake", "сидоров сидор"), "Сидоров Сидор", "Смирнов Алексей", "fake")
    s.add((E.SNILS, "hash", "12345678901"), "123-456-789 01", "СНИЛС_a3f91c07e2", "hash")
    s.add((E.ORG, "pseudonym", "ооо «а&б»"), "ООО «А&Б»", "Организация_0001", "pseudonym")
    return s


ENT = "".join(f"&#{ord(c)};" for c in "Персона")
ESC = "".join(f"\\u{ord(c):04x}" for c in "Персона")


def test_a9_html(tmp_path) -> None:
    src, out = tmp_path / "dash.html", tmp_path / "out.html"
    src.write_text(
        "<p>Менеджер: Персона_0017; клиент Смирнов Алексей; СНИЛС_a3f91c07e2</p>\n"
        f"<p>{ENT}_0017 и {ENT}_00170, ещё Персона_0099, Email_face</p>\n"
        f'<script>const d = {{"name": "{ESC}_0017", "org": "Организация_0001"}};</script>\n',
        "utf-8",
    )
    report = unmask_file(src, out, reload(a9_store()))
    text = out.read_text("utf-8")
    assert "<p>Менеджер: Иванов Иван; клиент Сидоров Сидор; 123-456-789 01</p>" in text
    assert "<p>Иванов Иван и" in text and f"{ENT}_00170" in text  # 0017 не задел 00170
    assert (
        '"name": "\\u0418\\u0432\\u0430\\u043d\\u043e\\u0432 \\u0418\\u0432\\u0430\\u043d"' in text
    )
    assert "ООО «А&amp;Б»" in text  # в HTML значение экранируется
    assert "Персона_0099" in text and "Email_face" in text
    assert report["tokens_replaced"] == 5 and report["fakes_replaced"] == 1
    assert report["unknown_tokens"] == 2
    assert set(report["unknown_sample"]) == {"Персона_00170", "Персона_0099"}


def test_a9_json(tmp_path) -> None:
    src, out = tmp_path / "data.json", tmp_path / "out.json"
    src.write_text(
        '{"rows": [{"manager": "' + ESC + '_0017", "' + ESC + '_0017": 5, "n": 1}],'
        ' "note": "Персона_00170 и Смирнов Алексей"}',
        "utf-8",
    )
    unmask_file(src, out, reload(a9_store()))
    data = json.loads(out.read_text("utf-8"))
    assert data == {
        "rows": [{"manager": "Иванов Иван", "Иванов Иван": 5, "n": 1}],
        "note": "Персона_00170 и Сидоров Сидор",
    }


def test_text_and_md_keep_encoding(tmp_path) -> None:
    for name, enc in (("a.txt", "cp1251"), ("b.md", "utf-8")):
        src, out = tmp_path / name, tmp_path / f"out_{name}"
        src.write_bytes("# Отчёт\r\nПерсона_0017 — лучший менеджер\r\n".encode(enc))
        unmask_file(src, out, a9_store())
        assert out.read_bytes() == "# Отчёт\r\nИванов Иван — лучший менеджер\r\n".encode(enc)


def test_custom_prefix_and_longest_fake_first() -> None:
    s = MappingStore(SECRET)
    s.add((E.PERSON, "pseudonym", "a"), "Анна", "Клиент_0001", "pseudonym")
    s.add((E.PERSON, "fake", "b"), "Борис", "Смирнов Алексей", "fake")
    s.add((E.PERSON, "fake", "c"), "Вера", "Смирнов Алексей Петрович", "fake")
    u = Unmasker(s)
    assert u.text("Клиент_0001, Смирнов Алексей Петрович, Смирнов Алексей.") == "Анна, Вера, Борис."
    assert u.text("НеКлиент_0001 Клиент_0001x") == "НеКлиент_0001 Клиент_0001x"


def test_project_store_keeps_secret_and_terms() -> None:
    s = MappingStore(SECRET)
    s.custom_terms = ["Ромашка"]
    shift = s.date_shift("Лист!B", {"sheet": "Лист", "column": "B", "header": "Д.р."})
    exported = MappingStore.decrypt(s.encrypt(PASSWORD), PASSWORD)
    assert exported.secret == b"" and exported.custom_terms == ["Ромашка"]
    project = MappingStore.decrypt(s.encrypt(PASSWORD, include_secret=True), PASSWORD)
    assert project.secret == SECRET
    assert project.date_shift("Лист!B", {}) == shift
    assert project.date_shifts["Лист!B"]["columns"] == [
        {"sheet": "Лист", "column": "B", "header": "Д.р."}
    ]


def test_unsupported_extension(tmp_path) -> None:
    from datamask.formats.base import FormatError

    f = tmp_path / "a.docx"
    f.write_bytes(b"x")
    with pytest.raises(FormatError):
        unmask_file(f, tmp_path / "o.docx", a9_store())


def test_dates_are_datetimes_after_restore(fixtures, tmp_path) -> None:
    masked, restored = tmp_path / "m.xlsx", tmp_path / "r.xlsx"
    _, store = run(fixtures / "clients.xlsx", masked, XLSX_CONFIG)
    unmask_file(masked, restored, store)
    assert isinstance(load_workbook(restored)["Клиенты"]["G4"].value, datetime)


def test_store_without_fakes() -> None:
    """Регулярка без группы фейков: раньше падало на первом же токене."""
    s = MappingStore(SECRET)
    s.add((E.PERSON, "pseudonym", "иванов иван"), "Иванов Иван", "Персона_0017", "pseudonym")
    u = Unmasker(s)
    assert u.text("Персона_0017 и Персона_0018") == "Иванов Иван и Персона_0018"
    assert u.html("<td>Персона_0017</td>") == "<td>Иванов Иван</td>"
