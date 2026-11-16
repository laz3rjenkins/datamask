"""Потоковое чтение и запись XLSX: то же, что дал бы openpyxl, на любой допустимой разметке."""

import dataclasses
import json
import re
import zipfile
from datetime import date, datetime

from mask_helpers import CLIENTS_CONFIG, col, leaks, run, zip_text
from openpyxl import Workbook, load_workbook

from datamask.core.models import kind_of
from datamask.core.pipeline import sample_sheet
from datamask.detectors.headers import thresholds
from datamask.formats import adapter_for
from datamask.formats.base import OpenOptions
from datamask.formats.xlsx import XlsxAdapter

XLSX = XlsxAdapter()
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def openpyxl_cells(path):
    """(лист, строка, колонка) → (значение, тип) по полной загрузке openpyxl."""
    out = {}
    for ws in load_workbook(path).worksheets:
        for (r, c), cell in ws._cells.items():
            v = cell.value
            if v is None or v == "":
                continue
            kind = {"f": "formula", "e": "error"}.get(cell.data_type) or kind_of(v)
            out[(ws.title, r, c)] = (v if kind != "formula" else str(v), kind)
    return out


def stream_cells(path):
    doc = XLSX.open(path, OpenOptions())
    return {
        (c.sheet, c.row, c.col): (c.value, c.kind)
        for s in doc.sheets
        for c in XLSX.iter_cells(doc, s.name)
    }


def test_reader_matches_openpyxl(fixtures) -> None:
    labels = json.loads((fixtures / "labeled" / "labels.json").read_text("utf-8"))
    books = [fixtures / "clients.xlsx"]
    books += [fixtures / "labeled" / i["file"] for i in labels if i["file"].endswith(".xlsx")]
    assert len(books) > 5
    for path in books:
        assert stream_cells(path) == openpyxl_cells(path), path.name


# ---------- нестандартная, но допустимая разметка ----------

SST = (
    f'<sst xmlns="{MAIN}" count="4" uniqueCount="4">'
    "<si><t>ФИО</t></si>"
    "<si><t>Телефон</t></si>"
    '<si><r><rPr><b/></rPr><t>Иванов </t></r><r><t xml:space="preserve">Иван</t></r>'
    "<rPh sb='0' eb='1'><t>ИГНОР</t></rPh></si>"
    "<si><t>Петров &amp; Ко</t></si>"
    "</sst>"
)
SHEET = (
    f'<x:worksheet xmlns:x="{MAIN}" xmlns:r="{R}" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" '
    'mc:Ignorable="x14ac"><x:dimension ref="A1:F3"/><x:sheetData>'
    '<x:row r="1" x14ac:dyDescent="0.25">'
    '<x:c r="A1" t="s"><x:v>0</x:v></x:c><x:c r="B1" t="s"><x:v>1</x:v></x:c>'
    '<x:c r="C1" t="inlineStr"><x:is><x:t>Дата</x:t></x:is></x:c>'
    '<x:c r="D1" t="inlineStr"><x:is><x:t>Формула</x:t></x:is></x:c></x:row>'
    # ячейки без r, атрибуты в другом порядке и в одинарных кавычках, cm
    "<x:row r='2'><x:c t='s' s='0'><x:v>2</x:v></x:c>"
    '<x:c t="inlineStr" cm="1"><x:is><x:r><x:t>8 912 123-45-67</x:t></x:r></x:is></x:c>'
    '<x:c s="1"><x:v>1</x:v></x:c>'
    '<x:c t="str"><x:f t="shared" ref="D2:D3" si="0">A2&amp;" "&amp;B2</x:f>'
    "<x:v>Иванов Иван 8 912 123-45-67</x:v></x:c>"
    '<x:c t="d"><x:v>2026-03-04T00:00:00</x:v></x:c>'
    '<x:c t="b"><x:v>1</x:v></x:c></x:row>'
    '<x:row r="3"><x:c r="A3" t="s"><x:v>3</x:v></x:c>'
    '<x:c r="B3" t="inlineStr"><x:is><x:t>+79121234567</x:t></x:is></x:c>'
    '<x:c r="D3"><x:f t="shared" ref="D2:D3" si="0"/></x:c></x:row>'
    '</x:sheetData><x:hyperlinks><x:hyperlink ref="B3" r:id="rId1"/></x:hyperlinks>'
    "</x:worksheet>"
)


def write_odd_book(path) -> None:
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml."
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"
    files = {
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{ct}sheet.main+xml"/>'
            f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="{ct}worksheet+xml"/>'
            f'<Override PartName="/xl/styles.xml" ContentType="{ct}styles+xml"/>'
            f'<Override PartName="/xl/sharedStrings.xml" ContentType="{ct}sharedStrings+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            f'<Relationships xmlns="{pkg}"><Relationship Id="rId1" '
            f'Type="{rel}officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            f'<workbook xmlns="{MAIN}" xmlns:r="{R}"><workbookPr date1904="1"/>'
            '<sheets><sheet name="Данные" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            f'<Relationships xmlns="{pkg}">'
            f'<Relationship Id="rId1" Type="{rel}worksheet" Target="worksheets/sheet1.xml"/>'
            f'<Relationship Id="rId2" Type="{rel}styles" Target="styles.xml"/>'
            f'<Relationship Id="rId3" Type="{rel}sharedStrings" Target="sharedStrings.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/_rels/sheet1.xml.rels": (
            f'<Relationships xmlns="{pkg}"><Relationship Id="rId1" Type="{rel}hyperlink" '
            'Target="tel:+79121234567" TargetMode="External"/></Relationships>'
        ),
        "xl/styles.xml": (
            f'<styleSheet xmlns="{MAIN}"><fonts count="1"><font/></fonts>'
            '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
            '<borders count="1"><border/></borders>'
            '<cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2">'
            '<xf numFmtId="0"/><xf numFmtId="14" applyNumberFormat="1"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            "</styleSheet>"
        ),
        "xl/sharedStrings.xml": SST,
        "xl/worksheets/sheet1.xml": SHEET,
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)


def test_reader_odd_markup(tmp_path) -> None:
    path = tmp_path / "odd.xlsx"
    write_odd_book(path)
    cells = stream_cells(path)
    s = "Данные"
    assert cells[(s, 2, 1)] == ("Иванов Иван", "string")  # rich text без фонетики rPh
    assert cells[(s, 2, 2)] == ("8 912 123-45-67", "string")
    assert cells[(s, 2, 3)] == (datetime(1904, 1, 2), "date")  # эпоха 1904
    assert cells[(s, 2, 4)] == ('=A2&" "&B2', "formula")
    assert cells[(s, 2, 5)] == (datetime(2026, 3, 4), "date")
    assert cells[(s, 2, 6)] == (True, "bool")
    assert cells[(s, 3, 1)] == ("Петров & Ко", "string")
    assert cells[(s, 3, 4)][1] == "formula"
    preview = XLSX.preview(XLSX.open(path, OpenOptions()), s, None, 10)
    assert preview.rows[1].values[3] == '=A3&" "&B3'  # общая формула в предпросмотре


def test_mask_odd_markup(tmp_path) -> None:
    src, out = tmp_path / "odd.xlsx", tmp_path / "out.xlsx"
    write_odd_book(src)
    config = {"sheets": {"Данные": {"columns": {"A": col("PERSON"), "B": col("PHONE")}}}}
    result, _ = run(src, out, config)
    assert sum(c.replaced for c in result.columns) == 4
    ws = load_workbook(out)["Данные"]  # результат читается, хотя разметка была с префиксами
    assert ws["A2"].value == "Персона_0001" and ws["B2"].value.startswith("Телефон_")
    assert ws["C2"].value == datetime(1904, 1, 2)  # дата не сдвинулась из-за эпохи
    assert ws["D2"].value == '=A2&" "&B2' and ws["E2"].value == datetime(2026, 3, 4)
    assert ws["B3"].hyperlink is None
    text = zip_text(out)
    assert not leaks(text, ["Иванов", "8 912 123-45-67", "+79121234567", "Петров"])
    assert "cm=" not in text and "dyDescent" not in text


# ---------- устройство результата ----------


def test_output_structure(fixtures, tmp_path) -> None:
    out = tmp_path / "out.xlsx"
    run(fixtures / "clients.xlsx", out, CLIENTS_CONFIG)
    with zipfile.ZipFile(out) as z:
        sheets = [z.read(n) for n in z.namelist() if n.startswith("xl/worksheets/sheet")]
        sst = z.read("xl/sharedStrings.xml")
    formulas = [c for x in sheets for c in re.findall(rb"<c [^>]*><f>.*?</c>", x)]
    assert formulas and not any(b"<v>" in f for f in formulas)  # кэш формул не переносится
    used = {int(i) for x in sheets for i in re.findall(rb't="s"><v>(\d+)</v>', x)}
    assert used == set(range(sst.count(b"<si>")))  # в таблице строк только используемые
    src = load_workbook(fixtures / "clients.xlsx")["Продажи"]
    res = load_workbook(out)["Продажи"]
    assert res.max_row == src.max_row and res.dimensions == src.dimensions


def test_csv_write_matches(fixtures, tmp_path) -> None:
    out = tmp_path / "out.csv"
    config = {"sheets": {"CSV": {"columns": {"2": col("PERSON")}}}}
    run(fixtures / "clients_utf8.csv", out, config)
    src = (fixtures / "clients_utf8.csv").read_bytes().splitlines()
    res = out.read_bytes().splitlines()
    assert len(src) == len(res) and src[0] == res[0] and src[1] != res[1]


# ---------- подсказки на больших листах ----------


def test_suggest_reads_only_first_rows(tmp_path, monkeypatch) -> None:
    path = tmp_path / "long.xlsx"
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Лист")
    ws.append(["Номер", "Расчёт"])
    for r in range(2, 702):
        ws.append([r, f"=A{r}*2"])
    wb.save(path)
    small = dataclasses.replace(thresholds(), scan_rows=100)
    monkeypatch.setattr("datamask.core.pipeline.thresholds", lambda: small)
    doc = adapter_for(path.name).open(path, OpenOptions())
    sample = sample_sheet(adapter_for(path.name), doc, "Лист", None)
    assert sample.formulas[2] == 100 and sample.non_empty[1] == 100


def test_suggest_cache_skips_rereading(make_client, fixtures, monkeypatch) -> None:
    from datamask.api import files

    calls = []
    real = files.sample_sheet
    monkeypatch.setattr(files, "sample_sheet", lambda *a: calls.append(a[2]) or real(*a))
    client = make_client()
    with (fixtures / "clients.xlsx").open("rb") as f:
        file_id = client.post("/api/files", files={"file": ("a.xlsx", f)}).json()["file_id"]
    for categories in ({"commercial": False}, {"commercial": True}, {"personal": False}):
        r = client.post(f"/api/files/{file_id}/suggest", json={"categories": categories})
        assert r.status_code == 200
    assert len(calls) == 4  # по разу на лист, смена категорий файл не перечитывает
    client.post(f"/api/files/{file_id}/suggest", json={"header_rows": {"Клиенты": 2}})
    assert calls[4:] == ["Клиенты"]


def test_date_cell_masked_keeps_style(fixtures, tmp_path) -> None:
    out = tmp_path / "out.xlsx"
    config = {
        "sheets": {"Продажи": {"columns": {"A": col("BIRTH_DATE", "date_shift")}}},
    }
    run(fixtures / "clients.xlsx", out, config)
    src = load_workbook(fixtures / "clients.xlsx")["Продажи"]["A2"]
    res = load_workbook(out)["Продажи"]["A2"]
    assert isinstance(res.value, datetime) and res.value.date() != src.value.date()
    assert res.number_format == src.number_format
    assert isinstance(src.value.date(), date)
