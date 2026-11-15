import json
from datetime import datetime

import pytest

from datamask.formats import adapter_for
from datamask.formats.base import FormatError, OpenOptions, detect_header_row
from datamask.formats.csv import CsvAdapter, detect_delimiter
from datamask.formats.xlsx import XlsxAdapter

XLSX, CSV = XlsxAdapter(), CsvAdapter()


def raw(*rows):
    return [[(v, "string" if isinstance(v, str) and v else "empty") for v in r] for r in rows]


def test_detect_header_row() -> None:
    assert detect_header_row(raw(["a", "b", "c"], ["1", "2", "3"])) == 1
    assert detect_header_row(raw(["Отчёт", None, None, None], [], ["a", "b", "c", "d"])) == 3
    assert detect_header_row(raw(["Отчёт", "за май"], ["a", "b", "c", "d", "e"])) == 2
    assert detect_header_row([]) == 1


def test_adapter_for_rejects_unsupported() -> None:
    assert adapter_for("Отчёт.XLSX") is not adapter_for("a.csv")
    with pytest.raises(FormatError, match="пересохраните|Пересохраните"):
        adapter_for("old.xls")
    with pytest.raises(FormatError, match="макрос"):
        adapter_for("m.xlsm")
    with pytest.raises(FormatError, match=r"\.xlsx и \.csv"):
        adapter_for("notes.txt")


def test_xlsx_sheets_and_risks(fixtures) -> None:
    doc = XLSX.open(fixtures / "clients.xlsx", OpenOptions())
    sheets = {s.name: s for s in doc.sheets}
    assert list(sheets) == ["Клиенты", "Продажи", "Архив", "Сводная"]
    assert sheets["Архив"].hidden and not sheets["Клиенты"].hidden
    assert sheets["Клиенты"].hidden_columns == ((10, 10),)
    assert sheets["Продажи"].rows == 61
    risks = {r.code: r for r in doc.risks}
    assert set(risks) == {
        "hidden_sheet",
        "hidden_columns",
        "comments",
        "images",
        "pivot_cache",
        "external_links",
    }
    assert risks["comments"].count == 2
    assert risks["hidden_sheet"].sheet == "Архив"


def test_xlsx_preview_dirty_sheet(fixtures) -> None:
    doc = XLSX.open(fixtures / "clients.xlsx", OpenOptions())
    p = XLSX.preview(doc, "Клиенты", None, 5)
    assert p.detected_header_row == p.header_row == 3
    assert [r.row for r in p.above_header] == [1, 2]
    assert p.columns[1].header == "ФИО"
    assert [c.key for c in p.columns if c.hidden] == ["J"]
    assert [r.row for r in p.rows] == [4, 5, 6, 7, 8]
    first = p.rows[0]
    assert first.kinds[0] == "number"
    assert first.kinds[6] == "date" and isinstance(first.values[6], datetime)
    assert first.kinds[11] == "formula" and str(first.values[11]).startswith("=B4&")
    assert all(len(r.values) == len(p.columns) for r in p.rows)


def test_xlsx_explicit_header_row(fixtures) -> None:
    doc = XLSX.open(fixtures / "clients.xlsx", OpenOptions())
    p = XLSX.preview(doc, "Клиенты", 1, 2)
    assert p.header_row == 1 and p.detected_header_row == 3
    assert p.columns[0].header.startswith("Выгрузка")
    assert [r.row for r in p.rows] == [2, 3]


def test_xlsx_iter_cells(fixtures) -> None:
    doc = XLSX.open(fixtures / "clients.xlsx", OpenOptions())
    cells = list(XLSX.iter_cells(doc, "Архив"))
    assert len(cells) == 21 * 3
    assert cells[0].row == 1 and cells[0].col == 1 and cells[0].value == "ФИО"
    assert all(c.kind != "empty" for c in cells)


def test_corrupt_xlsx(tmp_path) -> None:
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"PK\x03\x04 not really a zip")
    with pytest.raises(FormatError, match="повреждён"):
        XLSX.open(bad, OpenOptions())


@pytest.mark.parametrize(
    ("name", "encoding", "delimiter", "newline"),
    [
        ("clients_cp1251.csv", "cp1251", ";", "\r\n"),
        ("clients_utf8.csv", "utf-8-sig", ",", "\n"),
    ],
)
def test_csv_detection(fixtures, name, encoding, delimiter, newline) -> None:
    doc = CSV.open(fixtures / name, OpenOptions())
    assert (doc.encoding, doc.delimiter, doc.newline) == (encoding, delimiter, newline)
    p = CSV.preview(doc, "CSV", None, 200)
    assert p.header_row == 1
    assert [c.header for c in p.columns][:2] == ["Код филиала", "ФИО"]
    assert [c.key for c in p.columns][:2] == ["1", "2"]
    assert len(p.rows) == 30
    codes = [r.values[0] for r in p.rows]
    assert all(isinstance(c, str) and len(c) == 3 for c in codes)  # «007» не стало «7»
    assert any(str(c).startswith("0") for c in codes)
    assert all(len(r.values) == 7 for r in p.rows)  # запятые и кавычки внутри полей


def test_csv_manual_options(fixtures) -> None:
    doc = CSV.open(fixtures / "clients_cp1251.csv", OpenOptions(encoding="cp1251", delimiter=","))
    assert doc.delimiter == ","
    with pytest.raises(FormatError, match="кодировке"):
        CSV.open(fixtures / "clients_cp1251.csv", OpenOptions(encoding="utf-8"))
    with pytest.raises(FormatError, match="кодировка"):
        CSV.open(fixtures / "clients_cp1251.csv", OpenOptions(encoding="rot13"))


def test_csv_iter_cells_all_strings(fixtures) -> None:
    doc = CSV.open(fixtures / "clients_utf8.csv", OpenOptions())
    cells = list(CSV.iter_cells(doc, "CSV"))
    assert all(isinstance(c.value, str) and c.kind == "string" for c in cells)
    assert {c.row for c in cells} == set(range(1, 32))


def test_detect_delimiter_fallback() -> None:
    assert detect_delimiter("a|b|c\n1|2|3\n") == "|"
    assert detect_delimiter("одна колонка\nещё строка\n") in ",;\t|"


def test_header_row_detected_on_all_labeled_tables(fixtures) -> None:
    labels = json.loads((fixtures / "labeled" / "labels.json").read_text("utf-8"))
    assert len(labels) == 20
    for item in labels:
        path = fixtures / "labeled" / item["file"]
        adapter = adapter_for(path.name)
        doc = adapter.open(path, OpenOptions())
        p = adapter.preview(doc, item["sheet"], None, 10)
        assert p.header_row == item["header_row"], item["file"]
        assert [c.key for c in p.columns] == list(item["columns"]), item["file"]
