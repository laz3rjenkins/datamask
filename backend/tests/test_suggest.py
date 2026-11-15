"""A4 и эндпоинт подсказок."""

import json

from test_files_api import upload

from datamask.core.models import Category
from datamask.core.pipeline import enabled_detectors, suggest_sheet
from datamask.detectors.regex_ru import DETECTORS
from datamask.detectors.suggest import suggest_column
from datamask.formats import adapter_for
from datamask.formats.base import OpenOptions


def run_labeled(fixtures, categories):
    dets = enabled_detectors(categories, [])
    rows = []
    for item in json.loads((fixtures / "labeled" / "labels.json").read_text("utf-8")):
        path = fixtures / "labeled" / item["file"]
        adapter = adapter_for(path.name)
        res = suggest_sheet(adapter, adapter.open(path, OpenOptions()), item["sheet"], None, dets)
        for c in res.columns:
            got = c.suggestion.entity.value if c.suggestion else None
            rows.append((item["file"], c.key, item["columns"][c.key], got))
    return rows


def test_a4_recall_and_precision(fixtures) -> None:
    rows = run_labeled(fixtures, list(Category))
    labeled = [r for r in rows if r[2]]
    suggested = [r for r in rows if r[3]]
    correct = [r for r in labeled if r[2] == r[3]]
    wrong = [r for r in suggested if r[2] != r[3]]
    assert len(correct) / len(labeled) >= 0.95, [r for r in labeled if r[2] != r[3]]
    assert len(wrong) / len(suggested) <= 0.05, wrong


def test_categories_limit_suggestions(fixtures) -> None:
    rows = run_labeled(fixtures, [Category.PERSONAL, Category.FINANCIAL])
    commercial = {"ORG", "INN_ORG", "OGRN", "AMOUNT"}
    assert not [r for r in rows if r[3] in commercial]
    assert any(r[3] == "PERSON" for r in rows)


def test_suggest_column_reasons() -> None:
    values = ["8 912 123 45 67"] * 47 + ["нет"] * 3
    s = suggest_column("Тел.", values, DETECTORS)
    assert s and s.entity.value == "PHONE" and s.method == "pseudonym"
    assert s.confidence == 0.97
    assert s.reasons == ["заголовок «Тел.»", "47 из 50 значений похожи на тип «Телефон»"]


def test_weak_type_needs_header() -> None:
    names = ["Иванов Иван Иванович", "Петрова Анна Сергеевна"] * 10
    assert suggest_column("Колонка 1", names, DETECTORS) is None
    s = suggest_column("Ответственный", names, DETECTORS)
    assert s and s.entity.value == "PERSON"


def test_free_text_suggestion() -> None:
    texts = [
        f"Клиент просил перезвонить по номеру +7 912 123-45-{i:02d} после обеда" for i in range(9)
    ]
    texts.append("Без особых пожеланий, всё устраивает, спасибо за работу")
    s = suggest_column("Примечание к заказу", texts, DETECTORS)
    assert s and s.entity.value == "FREE_TEXT"
    short = ["+7 912 123-45-67 ок", "нет", "да"]  # средняя длина < 30
    assert suggest_column("Заметки", short, DETECTORS) is None


def test_suggest_endpoint_dirty_workbook(make_client, fixtures) -> None:
    client = make_client()
    file_id = upload(client, fixtures / "clients.xlsx").json()["file_id"]
    r = client.post(
        f"/api/files/{file_id}/suggest",
        json={"custom_terms": ["Подготовил", "Архив"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    sheets = {s["sheet"]: s for s in body["sheets"]}
    clients = sheets["Клиенты"]
    assert clients["header_row"] == 3
    got = {c["key"]: (c["suggestion"] or {}).get("entity") for c in clients["columns"]}
    assert got == {
        "A": None,
        "B": "PERSON",
        "C": "PHONE",
        "D": "EMAIL",
        "E": "INN_PERSON",
        "F": "SNILS",
        "G": "BIRTH_DATE",
        "H": "PASSPORT",
        "I": "ADDRESS",
        "J": None,
        "K": "FREE_TEXT",
        "L": None,
    }
    cols = {c["key"]: c for c in clients["columns"]}
    assert cols["G"]["suggestion"]["method"] == "date_shift"
    assert cols["L"]["formulas"] == 30 and cols["L"]["non_empty"] == 0
    assert clients["above_header"] == [{"entity": "CUSTOM", "count": 1}]

    archive = {
        c["header"]: (c["suggestion"] or {}).get("entity") for c in sheets["Архив"]["columns"]
    }
    assert archive == {"ФИО": "PERSON", "Телефон": "PHONE", "Дата рождения": "BIRTH_DATE"}
    sales = {
        c["header"]: (c["suggestion"] or {}).get("entity") for c in sheets["Продажи"]["columns"]
    }
    assert sales["Менеджер"] == "PERSON" and sales["Клиент"] == "PERSON"
    assert sales["Сумма"] is None  # «Коммерческие» по умолчанию выключены

    kinds = {(f["kind"], tuple(f["entities"])) for f in body["text_findings"]}
    assert ("comment", ("PHONE",)) in kinds
    assert ("sheet_name", ("CUSTOM",)) in kinds


def test_suggest_commercial_and_header_rows(make_client, fixtures) -> None:
    client = make_client()
    file_id = upload(client, fixtures / "clients.xlsx").json()["file_id"]
    r = client.post(
        f"/api/files/{file_id}/suggest",
        json={"categories": {"commercial": True}, "header_rows": {"Клиенты": 1}},
    )
    sheets = {s["sheet"]: s for s in r.json()["sheets"]}
    assert sheets["Клиенты"]["header_row"] == 1
    sales = {c["header"]: c["suggestion"] for c in sheets["Продажи"]["columns"]}
    assert sales["Сумма"]["entity"] == "AMOUNT" and sales["Сумма"]["method"] == "scale"

    r = client.post(f"/api/files/{file_id}/suggest", json={"header_rows": {"Нет": 1}})
    assert r.status_code == 404
    r = client.post(f"/api/files/{file_id}/suggest", json={"header_rows": {"Клиенты": 0}})
    assert r.status_code == 422


def test_suggest_csv(make_client, fixtures) -> None:
    client = make_client()
    file_id = upload(client, fixtures / "clients_cp1251.csv").json()["file_id"]
    body = client.post(f"/api/files/{file_id}/suggest", json={}).json()
    got = {c["key"]: (c["suggestion"] or {}).get("entity") for c in body["sheets"][0]["columns"]}
    assert got == {
        "1": None,
        "2": "PERSON",
        "3": "PHONE",
        "4": "EMAIL",
        "5": "BIRTH_DATE",
        "6": "ADDRESS",
        "7": "FREE_TEXT",
    }
    assert body["text_findings"] == []
