import logging
from urllib.parse import quote

UPLOAD_NAME = "Договор_Иванов_ЗАМЕТКА_7f3a.xlsx"


def upload(client, path, name=None):
    with path.open("rb") as f:
        return client.post("/api/files", files={"file": (name or path.name, f)})


def test_upload_xlsx(make_client, fixtures, session, caplog) -> None:
    client = make_client()
    with caplog.at_level(logging.INFO):
        r = upload(client, fixtures / "clients.xlsx", UPLOAD_NAME)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "xlsx" and body["csv"] is None
    assert [s["name"] for s in body["sheets"]] == ["Клиенты", "Продажи", "Архив", "Сводная"]
    assert {x["code"] for x in body["risks"]} >= {"hidden_sheet", "pivot_cache", "comments"}
    stored = list((session.path / "files").rglob("*"))
    assert any(p.name == "source.xlsx" for p in stored)
    # имя файла может содержать ПДн: ни на диске, ни в логах
    assert all("Иванов" not in str(p) for p in stored)
    assert "Иванов" not in caplog.text and "7f3a" not in caplog.text
    assert body["file_id"] in caplog.text


def test_upload_csv_and_change_options(make_client, fixtures) -> None:
    client = make_client()
    r = upload(client, fixtures / "clients_cp1251.csv")
    assert r.json()["csv"] == {"encoding": "cp1251", "delimiter": ";"}
    file_id = r.json()["file_id"]
    cols = client.get(f"/api/files/{file_id}/sheets/CSV/preview").json()["columns"]
    assert len(cols) == 7

    r = client.patch(f"/api/files/{file_id}", json={"delimiter": "|"})
    assert r.json()["csv"] == {"encoding": "cp1251", "delimiter": "|"}
    cols = client.get(f"/api/files/{file_id}/sheets/CSV/preview").json()["columns"]
    assert len(cols) == 1

    r = client.patch(f"/api/files/{file_id}", json={"encoding": "utf-8"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unreadable_file"


def test_patch_rejected_for_xlsx(make_client, fixtures) -> None:
    client = make_client()
    file_id = upload(client, fixtures / "clients.xlsx").json()["file_id"]
    assert client.patch(f"/api/files/{file_id}", json={"delimiter": ";"}).status_code == 400


def test_unsupported_formats(make_client, tmp_path) -> None:
    client = make_client()
    for name, words in [("old.xls", ".xlsx"), ("m.xlsm", "макрос"), ("a.docx", ".csv")]:
        f = tmp_path / name
        f.write_bytes(b"x")
        r = upload(client, f)
        assert r.status_code == 415
        assert words in r.json()["error"]["message"]


def test_too_large(make_client, tmp_path, session) -> None:
    client = make_client(max_upload_mb=1)
    f = tmp_path / "big.csv"
    f.write_bytes(b"a,b\n" * (2**20 // 2))
    r = upload(client, f)
    assert r.status_code == 413
    assert not list(session.path.rglob("*.csv"))


def test_corrupt_upload_cleans_up(make_client, tmp_path, session) -> None:
    client = make_client()
    f = tmp_path / "bad.xlsx"
    f.write_bytes(b"not a zip")
    r = upload(client, f)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "unreadable_file"
    assert list((session.path / "files").iterdir()) == []


def test_preview_endpoint(make_client, fixtures) -> None:
    client = make_client()
    file_id = upload(client, fixtures / "clients.xlsx").json()["file_id"]
    base = f"/api/files/{file_id}/sheets/{quote('Клиенты')}/preview"
    p = client.get(base).json()
    assert p["header_row"] == 3 and len(p["rows"]) == 30
    assert p["columns"][1] == {"index": 2, "key": "B", "header": "ФИО", "hidden": False}
    assert p["rows"][0]["kinds"][6] == "date"
    assert isinstance(p["rows"][0]["values"][6], str)  # дата в ISO

    p = client.get(base, params={"header_row": 1, "limit": 2}).json()
    assert p["header_row"] == 1 and len(p["rows"]) == 2

    assert client.get(base, params={"limit": 0}).status_code == 422
    r = client.get(f"/api/files/{file_id}/sheets/{quote('Нет такого')}/preview")
    assert r.status_code == 404 and r.json()["error"]["code"] == "sheet_not_found"
    r = client.get(f"/api/files/deadbeef/sheets/{quote('Клиенты')}/preview")
    assert r.status_code == 404 and r.json()["error"]["code"] == "file_not_found"


def test_clear_session_forgets_files(make_client, fixtures, session) -> None:
    client = make_client()
    file_id = upload(client, fixtures / "clients.xlsx").json()["file_id"]
    assert client.delete("/api/session").status_code == 200
    assert list(session.path.iterdir()) == []
    r = client.get(f"/api/files/{file_id}/sheets/{quote('Клиенты')}/preview")
    assert r.status_code == 404
