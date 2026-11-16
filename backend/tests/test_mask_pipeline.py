"""A1, A5, A6, A7, A11, A12 и поведение конвейера на «грязной» книге и CSV."""

import zipfile
from datetime import datetime

import pytest
from mask_helpers import CLIENTS_CONFIG, SECRET, col, leaks, run, soffice, soffice_opens, zip_text
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from datamask.core.models import EntityType, MaskConfig
from datamask.core.normalize import to_text
from datamask.core.pipeline import ConfigError, dry_run, summarize, validate_config
from datamask.detectors.base import DetectContext, find_spans
from datamask.detectors.regex_ru import DETECTORS
from datamask.formats import adapter_for
from datamask.formats.base import OpenOptions


@pytest.fixture(scope="module")
def masked(fixtures, tmp_path_factory):
    out = tmp_path_factory.mktemp("masked") / "out.xlsx"
    result, store = run(fixtures / "clients.xlsx", out, CLIENTS_CONFIG)
    return out, result, store


def selected_originals(src, config):
    """Строковые исходные значения выбранных колонок (+ найденные фрагменты свободного текста)."""
    wb = load_workbook(src)
    values = set()
    for sheet, sc in config["sheets"].items():
        ws = wb[sheet]
        for key, cc in sc["columns"].items():
            for cell in ws[key][sc["header_row"] :]:
                v = cell.value
                if (
                    not isinstance(v, str)
                    or v.startswith("=")
                    or cc["entity"] in ("BIRTH_DATE", "AMOUNT")
                ):
                    continue
                if cc["entity"] == "FREE_TEXT":
                    values |= {
                        v[s.start : s.end] for s in find_spans(v, DETECTORS, DetectContext())
                    }
                else:
                    values.add(v)
    return values


def test_a12_no_selected_originals_anywhere(fixtures, masked) -> None:
    out, _, _ = masked
    originals = selected_originals(fixtures / "clients.xlsx", CLIENTS_CONFIG)
    assert len(originals) > 150
    assert leaks(zip_text(out), originals) == []  # в т.ч. sharedStrings, гиперссылки, кэши


def test_a11_metadata_comments_pivot_chart_cleaned(fixtures, masked) -> None:
    out, result, _ = masked
    src = fixtures / "clients.xlsx"
    wb = load_workbook(src)
    secrets_ = {wb.properties.creator, wb.properties.lastModifiedBy, wb.properties.title}
    with zipfile.ZipFile(src) as z:
        app = z.read("docProps/app.xml").decode()
    secrets_.add(app.split("<Company>")[1].split("</Company>")[0])
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.comment:
                    secrets_ |= {cell.comment.author, cell.comment.text}
    # имена менеджеров лежали в кэше сводной и диаграммы
    secrets_ |= {c.value for c in wb["Продажи"]["B"][1:]}
    text = zip_text(out)
    assert leaks(text, secrets_) == []
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert not [n for n in names if "pivot" in n.lower() or "comment" in n.lower()]
    assert "fullCalcOnLoad" in text
    assert any("Сводные таблицы удалены" in a for a in result.actions)
    assert any("кэш данных в диаграммах" in a for a in result.actions)


def test_a1_consistency_across_sheets(fixtures, masked) -> None:
    out, _, _ = masked
    src_wb, out_wb = load_workbook(fixtures / "clients.xlsx"), load_workbook(out)
    pairs = []  # (исходник, результат) для всех ФИО полной формы на трёх листах
    for sheet, column, first in [("Клиенты", "B", 4), ("Продажи", "B", 2), ("Архив", "A", 2)]:
        src_col, out_col = src_wb[sheet][column][first - 1 :], out_wb[sheet][column][first - 1 :]
        pairs += [(s.value, o.value) for s, o in zip(src_col, out_col, strict=True)]
    forward, backward = {}, {}
    for s, o in pairs:
        assert forward.setdefault(s, o) == o  # одно значение → один псевдоним
        assert backward.setdefault(o, s) == s  # разные значения → разные псевдонимы
    assert len({s for s, _ in pairs}) == len({o for _, o in pairs})
    overlap = {s for s, _ in pairs[:30]} & {s for s, _ in pairs[90:]}
    assert overlap  # люди действительно повторяются между листами


def test_a5_formatting_preserved(fixtures, masked) -> None:
    out, _, _ = masked
    a, b = load_workbook(fixtures / "clients.xlsx"), load_workbook(out)
    allowed = {  # где значения могут меняться
        sheet: {(key, sc["header_row"]) for key in sc["columns"]}
        for sheet, sc in CLIENTS_CONFIG["sheets"].items()
    }
    for ws in a.worksheets:
        wo = b[ws.title]
        assert wo.merged_cells.ranges == ws.merged_cells.ranges
        assert wo.freeze_panes == ws.freeze_panes
        assert wo.auto_filter.ref == ws.auto_filter.ref
        assert wo.sheet_state == ws.sheet_state
        for key, dim in ws.column_dimensions.items():
            assert wo.column_dimensions[key].width == dim.width
            assert wo.column_dimensions[key].hidden == dim.hidden
        for row in ws.iter_rows():
            for c in row:
                o = wo[c.coordinate]
                for attr in ("font", "fill", "border", "alignment", "protection"):
                    assert repr(getattr(o, attr)) == repr(getattr(c, attr)), (c.coordinate, attr)
                assert o.number_format == c.number_format
                changed = o.value != c.value
                in_masked_col = any(
                    get_column_letter(c.column) == k and c.row > hr
                    for k, hr in allowed.get(ws.title, set())
                )
                above = ws.title == "Клиенты" and c.row < 3
                pivot_sweep = ws.title == "Сводная" and get_column_letter(c.column) == "A"
                if changed:
                    assert in_masked_col or above or pivot_sweep, (ws.title, c.coordinate)
                if isinstance(c.value, str) and c.value.startswith("="):
                    assert o.value == c.value  # формулы сохранены
    assert b["Клиенты"]["L4"].value.startswith("=B4&")
    assert b["Клиенты"]["A4"].value == 1


def test_a7_types_preserved(fixtures, masked) -> None:
    out, _, _ = masked
    a, b = load_workbook(fixtures / "clients.xlsx"), load_workbook(out)
    for r in range(4, 34):
        assert isinstance(b["Клиенты"].cell(r, 7).value, datetime)
        assert b["Клиенты"].cell(r, 7).value != a["Клиенты"].cell(r, 7).value
    for r in range(2, 62):
        assert isinstance(b["Продажи"].cell(r, 4).value, int | float)  # 1.0 Excel хранит как 1
    ratio = [b["Продажи"].cell(r, 4).value / a["Продажи"].cell(r, 4).value for r in range(2, 62)]
    assert max(ratio) - min(ratio) < 0.001  # один коэффициент на колонку: пропорции сохранены


def test_free_text_hyperlinks_custom_terms(fixtures, masked) -> None:
    out, result, _ = masked
    b = load_workbook(out)
    assert b["Клиенты"]["A2"].value == "Подготовил: Термин_0001"
    assert all(b["Клиенты"].cell(r, 4).hyperlink is None for r in range(4, 34))
    assert result.text_spans[EntityType.PHONE] > 0
    assert result.outside_selected == 4  # имена на листе бывшей сводной


def test_a6_libreoffice_opens(masked, tmp_path) -> None:
    if not soffice():
        pytest.skip("LibreOffice не установлен (A6 — вручную в Excel)")
    assert soffice_opens(masked[0], tmp_path)


def test_sanitize_options(fixtures, tmp_path) -> None:
    config = {
        "sheets": {"Клиенты": {"header_row": 3, "columns": {"K": col("FREE_TEXT")}}},
        "sanitize": {"comments": "keep", "hidden_sheets": "remove", "images": "remove"},
    }
    out = tmp_path / "o.xlsx"
    result, _ = run(fixtures / "clients.xlsx", out, config)
    b = load_workbook(out)
    assert "Архив" not in b.sheetnames
    assert not b["Клиенты"]._images
    comment = b["Клиенты"]["B4"].comment
    assert comment and comment.author == "datamask" and "Телефон_" in comment.text
    assert any("Удалены скрытые листы: 1" == a for a in result.actions)


def test_csv_preserves_encoding_delimiter_newlines(fixtures, tmp_path) -> None:
    src = fixtures / "clients_cp1251.csv"
    out = tmp_path / "o.csv"
    config = {
        "sheets": {
            "CSV": {
                "columns": {
                    "2": col("PERSON"),
                    "3": col("PHONE", "partial"),
                    "5": col("BIRTH_DATE", "date_shift"),
                    "7": col("FREE_TEXT"),
                }
            }
        }
    }
    run(src, out, config)
    raw = out.read_bytes()
    text = raw.decode("cp1251")
    assert text.count("\r\n") == src.read_bytes().decode("cp1251").count("\r\n")
    lines = text.split("\r\n")
    assert lines[0] == src.read_bytes().decode("cp1251").split("\r\n")[0]  # заголовок цел
    first = lines[1].split(";")
    original = src.read_bytes().decode("cp1251").split("\r\n")[1].split(";")
    assert first[0] == original[0] and first[0].startswith("0") or len(first[0]) == 3  # «007»
    assert first[1] == "Персона_0001"
    assert "*" in first[2]
    assert datetime.strptime(first[4], "%d.%m.%Y")  # дата — строка в том же формате
    assert first[4] != original[4]


def test_csv_utf8_bom_kept(fixtures, tmp_path) -> None:
    out = tmp_path / "o.csv"
    run(fixtures / "clients_utf8.csv", out, {"sheets": {"CSV": {"columns": {"2": col("PERSON")}}}})
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "\r\n" not in out.read_text("utf-8-sig")


def test_validate_config_errors(fixtures) -> None:
    adapter = adapter_for("a.xlsx")
    doc = adapter.open(fixtures / "clients.xlsx", OpenOptions())

    def check(config, match):
        with pytest.raises(ConfigError, match=match):
            validate_config(MaskConfig.model_validate(config), adapter, doc)

    check({"sheets": {"Нет": {}}}, "не найден")
    check({"sheets": {"Клиенты": {"columns": {"1A": col("PERSON")}}}}, "неверный адрес")
    check({"sheets": {"Клиенты": {"columns": {"D": col("EMAIL", "date_shift")}}}}, "не подходит")
    check({"sheets": {"Клиенты": {"columns": {"B": col("PERSON", prefix="Кли_ент")}}}}, "префикс")
    check(
        {"sheets": {"Клиенты": {"columns": {"C": col("PHONE", "partial", keep_last=99)}}}},
        "keep_last",
    )
    check({"consistency_scope": "project"}, "проект")


def test_dry_run_matches_real_run(fixtures, masked) -> None:
    adapter = adapter_for("a.xlsx")
    doc = adapter.open(fixtures / "clients.xlsx", OpenOptions())
    d = dry_run(adapter, doc, MaskConfig.model_validate(CLIENTS_CONFIG), SECRET)
    sheet = next(s for s in d.sheets if s.sheet == "Клиенты")
    assert [r.row for r in sheet.rows][:3] == [1, 2, 4]  # шапка + данные
    row4 = next(r for r in sheet.rows if r.row == 4)
    assert row4.after[1] == "Клиент_0001" and row4.changed[1]
    assert row4.changed[0] is False
    out = load_workbook(masked[0])["Клиенты"]
    assert row4.after[6] == out["G4"].value  # сдвиг дат тот же, что в результате (общий секрет)
    summary = {
        (s.sheet, s.key): s
        for s in summarize(adapter, doc, MaskConfig.model_validate(CLIENTS_CONFIG))
    }
    assert summary[("Клиенты", "B")].values == 30
    assert summary[("Клиенты", "L")].skipped_formulas == 30
    assert summary[("Продажи", "B")].unique == 4
    assert to_text(None) == ""
