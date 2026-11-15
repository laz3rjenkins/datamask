"""Синтетические тестовые таблицы (Faker ru_RU, фиксированный seed). Реальных данных тут нет.

    uv run python scripts/make_fixtures.py [папка]     # по умолчанию backend/tests/fixtures

Создаёт:
- clients.xlsx — «грязная» книга: шапка отчёта над заголовком, объединённые ячейки, скрытый
  лист и колонка, примечания, формулы, гиперссылки mailto, картинка, сводная таблица с кэшем,
  внешняя ссылка, метаданные с именами, именованный диапазон;
- clients_cp1251.csv (Windows-1251, «;», CRLF) и clients_utf8.csv (UTF-8 с BOM, «,», LF);
- labeled/ — 20 таблиц с разметкой колонок в labeled/labels.json (для теста автоподсказок A4).
"""

from __future__ import annotations

import csv
import io
import json
import random
import re
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from faker import Faker
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image
from openpyxl.styles import Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName

SEED = 20261115
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "backend" / "tests" / "fixtures"
EXTERNAL_PATH = "file:///C:/Users/smirnov.av/Documents/План_продаж.xlsx"


# ---------- люди ----------


@dataclass
class Person:
    last: str
    first: str
    middle: str
    phone: str
    email: str
    inn: str
    snils: str
    passport: str
    birth: date
    address: str
    card: str

    @property
    def fio(self) -> str:
        return f"{self.last} {self.first} {self.middle}"

    @property
    def short(self) -> str:
        return f"{self.last} {self.first[0]}.{self.middle[0]}."


def phone(fake: Faker, rnd: random.Random) -> str:
    d = "9" + "".join(rnd.choice("0123456789") for _ in range(9))
    return rnd.choice(
        [
            f"+7 ({d[:3]}) {d[3:6]}-{d[6:8]}-{d[8:]}",
            f"8 {d[:3]} {d[3:6]} {d[6:8]} {d[8:]}",
            f"8{d}",
            f"+7{d}",
            f"8-{d[:3]}-{d[3:6]}-{d[6:8]}-{d[8:]}",
        ]
    )


def snils(fake: Faker) -> str:
    s = fake.snils()
    return f"{s[:3]}-{s[3:6]}-{s[6:9]} {s[9:]}"


def person(fake: Faker, rnd: random.Random) -> Person:
    male = rnd.random() < 0.5
    sfx = "male" if male else "female"
    return Person(
        last=getattr(fake, f"last_name_{sfx}")(),
        first=getattr(fake, f"first_name_{sfx}")(),
        middle=getattr(fake, f"middle_name_{sfx}")(),
        phone=phone(fake, rnd),
        email=fake.free_email(),
        inn=fake.individuals_inn(),
        snils=snils(fake),
        passport=fake.passport_number(),
        birth=fake.date_of_birth(minimum_age=18, maximum_age=80),
        address=fake.address(),
        card=fake.credit_card_number(),
    )


def free_text(fake: Faker, rnd: random.Random, p: Person) -> str:
    return rnd.choice(
        [
            f"Перезвонить по номеру {p.phone} после 18:00, {fake.sentence(nb_words=5)}",
            f"Клиент просил присылать документы на {p.email}. {fake.sentence(nb_words=6)}",
            f"{fake.sentence(nb_words=8)} Запасной телефон: {phone(fake, rnd)}",
            f"Оплата картой, ИНН для чека {p.inn}. {fake.sentence(nb_words=4)}",
        ]
    )


# ---------- clients.xlsx ----------

BOLD = Font(bold=True)
HEAD_FILL = PatternFill("solid", fgColor="DDEBF7")


def write_clients_xlsx(path: Path, people: list[Person], fake: Faker, rnd: random.Random) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Клиенты"
    headers = [
        "№", "ФИО", "Телефон", "Email", "ИНН", "СНИЛС", "Дата рождения", "Паспорт",
        "Адрес", "Внутр. код", "Комментарий", "ФИО для писем",
    ]  # fmt: skip
    ws["A1"] = "Выгрузка клиентов на 01.11.2026"
    ws["A1"].font = Font(bold=True, size=14)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    ws["A2"] = "Подготовил: отдел продаж"
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(3, c, h)
        cell.font, cell.fill = BOLD, HEAD_FILL
    for i, p in enumerate(people[:30], start=1):
        r = i + 3
        ws.cell(r, 1, i)
        ws.cell(r, 2, p.fio)
        ws.cell(r, 3, p.phone)
        email = ws.cell(r, 4, p.email)
        email.hyperlink = f"mailto:{p.email}"
        ws.cell(r, 5, p.inn)
        ws.cell(r, 6, p.snils)
        ws.cell(r, 7, p.birth).number_format = "DD.MM.YYYY"
        ws.cell(r, 8, p.passport)
        ws.cell(r, 9, p.address)
        ws.cell(r, 10, f"K-{rnd.randint(1000, 9999)}")
        ws.cell(r, 11, free_text(fake, rnd, p))
        ws.cell(r, 12, f'=B{r}&" ("&D{r}&")"')
    ws.column_dimensions["J"].hidden = True
    for col, width in zip("BCDEFGHIKL", (34, 20, 28, 15, 16, 14, 14, 50, 60, 50), strict=True):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:L{len(people[:30]) + 3}"
    ws["B4"].comment = Comment(f"Постоянный клиент, тел. {people[0].phone}", people[5].short)
    ws["C6"].comment = Comment("Номер уточнить", people[6].short)

    sales = wb.create_sheet("Продажи")
    managers = people[30:34]
    for c, h in enumerate(["Дата", "Менеджер", "Клиент", "Сумма", "Регион"], start=1):
        sales.cell(1, c, h).font = BOLD
    totals: dict[str, float] = {}
    for r in range(2, 62):
        m = rnd.choice(managers)
        amount = round(rnd.uniform(1_000, 250_000), 2)
        totals[m.fio] = totals.get(m.fio, 0) + amount
        sales.cell(
            r, 1, date(2026, 1, 1) + timedelta(days=rnd.randint(0, 300))
        ).number_format = "DD.MM.YYYY"
        sales.cell(r, 2, m.fio)
        sales.cell(r, 3, rnd.choice(people[:30]).short)
        sales.cell(r, 4, amount).number_format = "#,##0.00"
        sales.cell(r, 5, fake.region())
    sales.column_dimensions["B"].width = 34

    archive = wb.create_sheet("Архив")
    archive.sheet_state = "hidden"
    archive.append(["ФИО", "Телефон", "Дата рождения"])
    for p in people[20:40]:  # часть людей повторяется с «Клиентами» и «Продажами»
        archive.append([p.fio, p.phone, p.birth])

    pivot = wb.create_sheet("Сводная")
    pivot["A3"], pivot["B3"] = "Названия строк", "Сумма по полю Сумма"
    names = sorted(totals)
    for i, n in enumerate(names, start=4):
        pivot.cell(i, 1, n)
        pivot.cell(i, 2, round(totals[n], 2))
    pivot.cell(len(names) + 4, 1, "Общий итог")
    pivot.cell(len(names) + 4, 2, round(sum(totals.values()), 2))

    img = io.BytesIO()
    from PIL import Image as PILImage

    PILImage.new("RGB", (40, 20), "white").save(img, "PNG")
    ws.add_image(Image(img), "N4")

    wb.defined_names[f"Клиенты_{people[0].last}"] = DefinedName(
        f"Клиенты_{people[0].last}", attr_text="Клиенты!$B$4:$B$33"
    )
    wb.properties.creator = people[34].fio
    wb.properties.lastModifiedBy = people[35].fio
    wb.properties.title = f"Клиенты менеджера {managers[0].short}"
    buf = io.BytesIO()
    wb.save(buf)

    pivot_rows = [(r[1].value, r[3].value) for r in sales.iter_rows(min_row=2)]
    path.write_bytes(_add_pivot_and_extras(buf.getvalue(), pivot_rows, people[36].fio))


def _add_pivot_and_extras(xlsx: bytes, rows: list[tuple[str, float]], company: str) -> bytes:
    """Дописывает в книгу то, что openpyxl создавать не умеет: сводную с кэшем исходных данных,
    внешнюю ссылку, компанию в docProps/app.xml."""
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    r_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml."
    names = sorted({n for n, _ in rows})
    idx = {n: i for i, n in enumerate(names)}
    amounts = [a for _, a in rows]

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")

    cache_def = (
        f'<pivotCacheDefinition xmlns="{main}" xmlns:r="{r_ns}" r:id="rId1" refreshOnLoad="1" '
        f'recordCount="{len(rows)}"><cacheSource type="worksheet">'
        f'<worksheetSource ref="A1:E{len(rows) + 1}" sheet="Продажи"/></cacheSource>'
        f'<cacheFields count="2"><cacheField name="Менеджер" numFmtId="0">'
        f'<sharedItems count="{len(names)}">'
        + "".join(f'<s v="{esc(n)}"/>' for n in names)
        + '</sharedItems></cacheField><cacheField name="Сумма" numFmtId="0">'
        '<sharedItems containsSemiMixedTypes="0" containsString="0" containsNumber="1" '
        f'minValue="{min(amounts)}" maxValue="{max(amounts)}"/></cacheField></cacheFields>'
        "</pivotCacheDefinition>"
    )
    records = (
        f'<pivotCacheRecords xmlns="{main}" count="{len(rows)}">'
        + "".join(f'<r><x v="{idx[n]}"/><n v="{a}"/></r>' for n, a in rows)
        + "</pivotCacheRecords>"
    )
    row_items = "".join(
        "<i><x/></i>" if i == 0 else f'<i><x v="{i}"/></i>' for i in range(len(names))
    )
    table = (
        f'<pivotTableDefinition xmlns="{main}" name="Сводная1" cacheId="1" '
        'dataCaption="Значения" applyNumberFormats="0" applyBorderFormats="0" '
        'applyFontFormats="0" applyPatternFormats="0" applyAlignmentFormats="0" '
        'applyWidthHeightFormats="1" updatedVersion="6" minRefreshableVersion="3" '
        'createdVersion="6" useAutoFormatting="1" itemPrintTitles="1" indent="0" outline="1" '
        f'outlineData="1"><location ref="A3:B{len(names) + 4}" firstHeaderRow="1" '
        'firstDataRow="1" firstDataCol="1"/><pivotFields count="2">'
        f'<pivotField axis="axisRow" showAll="0"><items count="{len(names) + 1}">'
        + "".join(f'<item x="{i}"/>' for i in range(len(names)))
        + '<item t="default"/></items></pivotField><pivotField dataField="1" showAll="0"/>'
        f'</pivotFields><rowFields count="1"><field x="0"/></rowFields>'
        f'<rowItems count="{len(names) + 1}">{row_items}<i t="grand"><x/></i></rowItems>'
        '<colItems count="1"><i/></colItems><dataFields count="1">'
        '<dataField name="Сумма по полю Сумма" fld="1" baseField="0" baseItem="0"/>'
        "</dataFields></pivotTableDefinition>"
    )
    ext_link = (
        f'<externalLink xmlns="{main}" xmlns:r="{r_ns}"><externalBook r:id="rId1">'
        '<sheetNames><sheetName val="Лист1"/></sheetNames></externalBook></externalLink>'
    )

    def rels(*items: tuple[str, str, str, str]) -> str:
        body = "".join(
            f'<Relationship Id="{i}" Type="{rel}{t}" Target="{esc(tg)}"'
            + (' TargetMode="External"' if ext else "")
            + "/>"
            for i, t, tg, ext in items
        )
        return (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{body}</Relationships>"
        )

    src = zipfile.ZipFile(io.BytesIO(xlsx))
    files = {n: src.read(n) for n in src.namelist()}
    wb_xml = files["xl/workbook.xml"].decode()
    sheet_names = re.findall(r'<sheet [^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', wb_xml)
    wb_rels = files["xl/_rels/workbook.xml.rels"].decode()
    pivot_rid = dict(sheet_names)["Сводная"]
    pivot_sheet = re.search(rf'Id="{pivot_rid}"[^>]*Target="/?(?:xl/)?([^"]+)"', wb_rels)
    if not pivot_sheet:  # порядок атрибутов может быть другим
        pivot_sheet = re.search(rf'Target="/?(?:xl/)?([^"]+)"[^>]*Id="{pivot_rid}"', wb_rels)
    assert pivot_sheet
    sheet_part = "xl/" + pivot_sheet.group(1)
    sheet_rels = f"xl/worksheets/_rels/{Path(sheet_part).name}.rels"
    assert sheet_rels not in files

    files["xl/pivotCache/pivotCacheDefinition1.xml"] = cache_def.encode()
    files["xl/pivotCache/pivotCacheRecords1.xml"] = records.encode()
    files["xl/pivotCache/_rels/pivotCacheDefinition1.xml.rels"] = rels(
        ("rId1", "pivotCacheRecords", "pivotCacheRecords1.xml", "")
    ).encode()
    files["xl/pivotTables/pivotTable1.xml"] = table.encode()
    files["xl/pivotTables/_rels/pivotTable1.xml.rels"] = rels(
        ("rId1", "pivotCacheDefinition", "../pivotCache/pivotCacheDefinition1.xml", "")
    ).encode()
    files[sheet_rels] = rels(("rId1", "pivotTable", "../pivotTables/pivotTable1.xml", "")).encode()
    files["xl/externalLinks/externalLink1.xml"] = ext_link.encode()
    files["xl/externalLinks/_rels/externalLink1.xml.rels"] = rels(
        ("rId1", "externalLinkPath", EXTERNAL_PATH, "1")
    ).encode()

    files["xl/_rels/workbook.xml.rels"] = wb_rels.replace(
        "</Relationships>",
        f'<Relationship Id="rIdPC1" Type="{rel}pivotCacheDefinition" '
        'Target="pivotCache/pivotCacheDefinition1.xml"/>'
        f'<Relationship Id="rIdEL1" Type="{rel}externalLink" '
        'Target="externalLinks/externalLink1.xml"/></Relationships>',
    ).encode()
    # Порядок элементов workbook важен: externalReferences после sheets, pivotCaches после calcPr.
    wb_xml = wb_xml.replace(
        "</sheets>",
        '</sheets><externalReferences><externalReference r:id="rIdEL1"/></externalReferences>',
    )
    calc = re.search(r"<calcPr[^>]*/>", wb_xml)
    assert calc
    wb_xml = wb_xml.replace(
        calc.group(0),
        calc.group(0) + '<pivotCaches><pivotCache cacheId="1" r:id="rIdPC1"/></pivotCaches>',
    )
    files["xl/workbook.xml"] = wb_xml.encode()

    types = files["[Content_Types].xml"].decode()
    overrides = [
        ("/xl/pivotCache/pivotCacheDefinition1.xml", "pivotCacheDefinition+xml"),
        ("/xl/pivotCache/pivotCacheRecords1.xml", "pivotCacheRecords+xml"),
        ("/xl/pivotTables/pivotTable1.xml", "pivotTable+xml"),
        ("/xl/externalLinks/externalLink1.xml", "externalLink+xml"),
    ]
    files["[Content_Types].xml"] = types.replace(
        "</Types>",
        "".join(f'<Override PartName="{p}" ContentType="{ct}{t}"/>' for p, t in overrides)
        + "</Types>",
    ).encode()

    app = files["docProps/app.xml"].decode()
    if "<Company>" not in app:
        app = app.replace("</Properties>", f"<Company>{esc(company)}</Company></Properties>")
    files["docProps/app.xml"] = app.encode()

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


# ---------- clients CSV ----------


def write_clients_csv(
    path: Path, people: list[Person], fake: Faker, rnd: random.Random, enc: str, delim: str, nl: str
) -> None:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, delimiter=delim, lineterminator=nl)
    w.writerow(["Код филиала", "ФИО", "Телефон", "Email", "Дата рождения", "Адрес", "Комментарий"])
    for p in people[:30]:
        w.writerow(
            [
                f"{rnd.randint(1, 99):03d}",  # «007» не должно стать «7»
                p.fio,
                p.phone,
                p.email,
                p.birth.strftime("%d.%m.%Y"),
                p.address,  # запятые внутри поля
                free_text(fake, rnd, p) + ' «цитата» и "кавычки"',
            ]
        )
    path.write_bytes(buf.getvalue().encode(enc))


# ---------- размеченные таблицы для A4 ----------


@dataclass(frozen=True)
class ColumnSpec:
    label: str | None  # тип из SPEC §8; None — колонка без ПДн (ложная подсказка = ошибка)
    headers: tuple[str, ...]
    kind: str  # имя генератора


CATALOG = [
    ColumnSpec("PERSON", ("ФИО", "Клиент", "Сотрудник", "Ответственный", "Full name"), "fio"),
    ColumnSpec("PERSON", ("Менеджер", "Фамилия И.О."), "short"),
    ColumnSpec("PHONE", ("Телефон", "Тел.", "Моб. телефон", "Phone", "Контактный номер"), "phone"),
    ColumnSpec("EMAIL", ("Email", "E-mail", "Почта", "Эл. почта"), "email"),
    ColumnSpec("INN_PERSON", ("ИНН", "ИНН физлица"), "inn"),
    ColumnSpec("SNILS", ("СНИЛС",), "snils"),
    ColumnSpec("PASSPORT", ("Паспорт", "Серия и номер паспорта"), "passport"),
    ColumnSpec("BIRTH_DATE", ("Дата рождения", "Д.р.", "Birth date"), "birth"),
    ColumnSpec("ADDRESS", ("Адрес", "Адрес доставки", "Address"), "address"),
    ColumnSpec("CARD", ("Номер карты", "Карта"), "card"),
    ColumnSpec("ACCOUNT", ("Расчётный счёт", "Р/с"), "account"),
    ColumnSpec("IP", ("IP", "IP-адрес"), "ip"),
    ColumnSpec("ORG", ("Организация", "Контрагент", "Company"), "company"),
    ColumnSpec("INN_ORG", ("ИНН организации", "ИНН контрагента"), "inn_org"),
    ColumnSpec("OGRN", ("ОГРН",), "ogrn"),
    ColumnSpec("AMOUNT", ("Сумма", "Выручка", "Сумма, руб."), "amount"),
    ColumnSpec("FREE_TEXT", ("Комментарий", "Примечание"), "free_text"),
    # без ПДн — ловушки для ложных подсказок
    ColumnSpec(None, ("Номер заказа", "Order ID"), "order_no"),
    ColumnSpec(None, ("Артикул",), "sku"),
    ColumnSpec(None, ("Количество", "Qty"), "qty"),
    ColumnSpec(None, ("Дата заказа", "Дата отгрузки"), "order_date"),
    ColumnSpec(None, ("Статус",), "status"),
    ColumnSpec(None, ("Товар", "Наименование товара"), "product"),
    ColumnSpec(None, ("Скидка, %",), "discount"),
    ColumnSpec(None, ("Код региона",), "region_code"),
]

STATUSES = ("Новый", "В работе", "Оплачен", "Отгружен", "Отменён")
PRODUCTS = ("Ноутбук", "Монитор", "Клавиатура", "Мышь", "Кабель HDMI", "Принтер", "Сканер")


def value(kind: str, fake: Faker, rnd: random.Random, p: Person, as_csv: bool) -> object:
    d: object
    match kind:
        case "fio":
            return p.fio
        case "short":
            return p.short
        case "phone":
            return p.phone
        case "email":
            return p.email
        case "inn":
            return p.inn
        case "snils":
            return p.snils
        case "passport":
            return p.passport
        case "birth":
            d = p.birth
        case "address":
            return p.address
        case "card":
            return p.card
        case "account":
            return fake.checking_account()
        case "ip":
            return fake.ipv4_public()
        case "company":
            return fake.company()
        case "inn_org":
            return fake.businesses_inn()
        case "ogrn":
            return fake.businesses_ogrn()
        case "amount":
            amount = round(rnd.uniform(100, 500_000), 2)
            return f"{amount:.2f}".replace(".", ",") if as_csv else amount
        case "free_text":
            return free_text(fake, rnd, p)
        case "order_no":
            return str(rnd.randint(10**9, 10**10 - 1))
        case "sku":
            return f"ART-{rnd.randint(10000, 99999)}"
        case "qty":
            q = rnd.randint(1, 500)
            return str(q) if as_csv else q
        case "order_date":
            d = datetime(2026, 1, 1) + timedelta(days=rnd.randint(0, 300))
        case "status":
            return rnd.choice(STATUSES)
        case "product":
            return rnd.choice(PRODUCTS)
        case "discount":
            q = rnd.choice([0, 5, 10, 15])
            return str(q) if as_csv else q
        case "region_code":
            return f"{rnd.randint(1, 99):02d}"
        case _:
            raise ValueError(kind)
    assert isinstance(d, date)
    return d.strftime("%d.%m.%Y") if as_csv else d


def write_labeled(out: Path, fake: Faker, rnd: random.Random) -> None:
    out.mkdir(parents=True, exist_ok=True)
    labels = []
    for t in range(1, 21):
        as_csv = t % 4 == 0  # каждая четвёртая — CSV
        pii = rnd.sample([c for c in CATALOG if c.label], rnd.randint(4, 8))
        decoys = rnd.sample([c for c in CATALOG if not c.label], rnd.randint(2, 4))
        specs = pii + decoys
        rnd.shuffle(specs)
        headers = [rnd.choice(s.headers) for s in specs]
        n_rows = rnd.randint(40, 300)
        people = [person(fake, rnd) for _ in range(max(10, n_rows // 3))]
        title = [] if t % 3 else [["Отчёт по клиентам за период"], []]  # шапка над заголовком
        body = []
        for _ in range(n_rows):
            p = rnd.choice(people)  # люди повторяются: так в реальных выгрузках
            body.append([value(s.kind, fake, rnd, p, as_csv) for s in specs])

        name = f"table_{t:02d}." + ("csv" if as_csv else "xlsx")
        if as_csv:
            buf = io.StringIO(newline="")
            w = csv.writer(buf, delimiter=";" if t % 8 == 0 else ",", lineterminator="\r\n")
            w.writerows(title + [headers] + body)
            (out / name).write_bytes(buf.getvalue().encode("cp1251" if t % 8 == 0 else "utf-8"))
            keys = [str(i) for i in range(1, len(specs) + 1)]
        else:
            wb = Workbook()
            ws = wb.active
            ws.title = "Данные"
            for row in title + [headers] + body:
                ws.append(row)
            wb.save(out / name)
            keys = [ws.cell(1, i).column_letter for i in range(1, len(specs) + 1)]
        labels.append(
            {
                "file": name,
                "sheet": "CSV" if as_csv else "Данные",
                "header_row": len(title) + 1,
                "columns": {k: s.label for k, s in zip(keys, specs, strict=True)},
            }
        )
    (out / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=1), "utf-8")


def generate(out: Path = DEFAULT_OUT) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    fake = Faker("ru_RU")
    fake.seed_instance(SEED)
    rnd = random.Random(SEED)
    people = [person(fake, rnd) for _ in range(40)]
    write_clients_xlsx(out / "clients.xlsx", people, fake, rnd)
    write_clients_csv(out / "clients_cp1251.csv", people, fake, rnd, "cp1251", ";", "\r\n")
    write_clients_csv(out / "clients_utf8.csv", people, fake, rnd, "utf-8-sig", ",", "\n")
    write_labeled(out / "labeled", fake, rnd)
    return out


if __name__ == "__main__":
    print(generate(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT))
