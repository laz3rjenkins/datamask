"""Эндпоинты для интерфейса (M5): справочник, находки в имени файла, подсветка находок."""

from urllib.parse import quote

from test_files_api import upload


def test_meta(make_client) -> None:
    m = make_client().get("/api/meta").json()
    ent = {e["value"]: e for e in m["entities"]}
    assert ent["PHONE"]["label"] == "Телефон" and ent["PHONE"]["category"] == "personal"
    assert "partial" in ent["PHONE"]["methods"] and "date_shift" not in ent["PHONE"]["methods"]
    assert ent["BIRTH_DATE"]["default_method"] == "date_shift"
    assert ent["FREE_TEXT"]["category"] is None
    assert ent["FREE_TEXT"]["methods"] == ["pseudonym", "hash", "label", "delete"]
    rev = {x["value"]: x["reversible"] for x in m["methods"]}
    assert rev["pseudonym"] and not rev["noise"]
    assert m["min_password"] == 10 and m["max_upload_mb"] == 50
    assert make_client(authed=False).get("/api/meta").status_code == 401


def test_name_findings(make_client, fixtures) -> None:
    client = make_client()
    r = upload(client, fixtures / "clients.xlsx", "Выгрузка_+79121234567.xlsx").json()
    assert r["name_findings"] == ["PHONE"]
    assert "79121234567" not in str(r)
    assert upload(client, fixtures / "clients.xlsx", "clients.xlsx").json()["name_findings"] == []


def test_spans(make_client, fixtures) -> None:
    client = make_client()
    file_id = upload(client, fixtures / "clients.xlsx").json()["file_id"]
    url = f"/api/files/{file_id}/sheets/{quote('Клиенты')}/spans"
    preview = client.get(f"/api/files/{file_id}/sheets/{quote('Клиенты')}/preview").json()
    free = next(c["key"] for c in preview["columns"] if c["header"] == "Комментарий")

    cells = client.post(url, json={"columns": [free]}).json()
    body = [c for c in cells if c["row"] > preview["header_row"]]
    assert body and all(c["col"] == ord(free) - 64 for c in body)
    row = next(r for r in preview["rows"] if r["row"] == body[0]["row"])
    text = row["values"][body[0]["col"] - 1]
    s = body[0]["spans"][0]
    assert 0 <= s["start"] < s["end"] <= len(text) and s["entity"]

    # без колонок и без шапки — пусто
    assert client.post(url, json={"scan_above_header": False}).json() == []
    assert client.post(url, json={"columns": ["1"]}).status_code == 422
    r = client.post(f"/api/files/{file_id}/sheets/{quote('Нет')}/spans", json={})
    assert r.status_code == 404
