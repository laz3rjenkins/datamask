"""Проекты и шаблоны через API (M6). A16: в папке данных нет открытых значений."""

import time

from mask_helpers import col
from openpyxl import load_workbook
from test_files_api import upload

PASSWORD = "пароль-проекта-1"


def wait(client, job_id):
    for _ in range(200):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.05)
    raise AssertionError("задача не завершилась")


def project_config(project_id):
    return {
        "consistency_scope": "project",
        "project_id": project_id,
        "sheets": {
            "Клиенты": {
                "header_row": 3,
                "columns": {
                    "B": col("PERSON"),
                    "C": col("PHONE", "fake"),
                    "G": col("BIRTH_DATE", "date_shift"),
                },
            }
        },
        "custom_terms": ["отдел продаж"],
    }


def mask(client, fixtures, config, password=PASSWORD):
    file_id = upload(client, fixtures / "clients.xlsx").json()["file_id"]
    return client.post(f"/api/files/{file_id}/mask", json={"config": config, "password": password})


def test_project_crud(make_client) -> None:
    client = make_client()
    assert client.get("/api/projects").json() == []
    r = client.post("/api/projects", json={"name": "  Клиент   А ", "password": PASSWORD})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["name"] == "Клиент А" and p["entries"] == 0
    assert client.get("/api/projects").json() == [p]
    r = client.post("/api/projects", json={"name": "клиент а", "password": PASSWORD})
    assert r.status_code == 422 and "уже есть" in r.json()["error"]["message"]
    r = client.post("/api/projects", json={"name": "Б", "password": "short"})
    assert r.status_code == 422
    assert client.delete("/api/projects/..secret").status_code == 404
    assert client.delete(f"/api/projects/{p['id']}").status_code == 200
    assert client.get("/api/projects").json() == []
    assert client.delete(f"/api/projects/{p['id']}").status_code == 404


def test_project_consistency_across_files(make_client, fixtures, tmp_path) -> None:
    client = make_client()
    pid = client.post("/api/projects", json={"name": "Клиент", "password": PASSWORD}).json()["id"]

    assert mask(client, fixtures, project_config(pid), "неверный-пароль").status_code == 422
    r = mask(client, fixtures, {**project_config(pid), "project_id": None})
    assert r.status_code == 422  # проект не выбран

    outs = []
    for _ in range(2):
        r = mask(client, fixtures, project_config(pid))
        assert r.status_code == 200, r.text
        job = wait(client, r.json()["job_id"])
        assert job["status"] == "done", job["error"]
        assert {"masked", "mapping"} <= set(job["artifacts"])
        path = tmp_path / f"{job['job_id']}.xlsx"
        path.write_bytes(client.get(f"/api/jobs/{job['job_id']}/download/masked").content)
        outs.append(load_workbook(path)["Клиенты"])
    # второй файл получил те же псевдонимы, фейки и сдвиг дат: значения уже известны проекту
    for c in ("B", "C", "G"):
        assert [x.value for x in outs[0][c]] == [x.value for x in outs[1][c]]
    meta = client.get("/api/projects").json()[0]
    assert meta["entries"] > 0


def test_a16_data_dir_has_no_plaintext(make_client, fixtures, tmp_path) -> None:
    client = make_client()
    pid = client.post("/api/projects", json={"name": "Клиент", "password": PASSWORD}).json()["id"]
    wait(client, mask(client, fixtures, project_config(pid)).json()["job_id"])
    ws = load_workbook(fixtures / "clients.xlsx")["Клиенты"]
    originals = [ws[f"B{r}"].value for r in range(4, 34)] + [
        ws[f"C{r}"].value for r in range(4, 34)
    ]
    originals.append("отдел продаж")  # свой словарь проекта тоже не лежит открыто
    data = b"".join(f.read_bytes() for f in (tmp_path / "data").rglob("*") if f.is_file())
    assert data
    assert [v for v in originals if v.encode() in data] == []


def test_templates(make_client) -> None:
    client = make_client()
    rules = [
        {
            "header": "ФИО",
            "entity": "PERSON",
            "method": "pseudonym",
            "params": {"prefix": "Клиент"},
        },
        {"header": "Тел.", "entity": "PHONE", "method": "partial"},
    ]
    r = client.post("/api/templates", json={"name": "Выгрузка CRM", "rules": rules})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["rules"][1]["params"] == {} and client.get("/api/templates").json() == [t]
    bad = [{"header": "Email", "entity": "EMAIL", "method": "date_shift"}]
    r = client.post("/api/templates", json={"name": "x", "rules": bad})
    assert r.status_code == 422 and "не подходит" in r.json()["error"]["message"]
    bad = [{"header": "ФИО", "entity": "PERSON", "method": "pseudonym", "params": {"prefix": "1"}}]
    assert client.post("/api/templates", json={"name": "x", "rules": bad}).status_code == 422
    assert client.delete(f"/api/templates/{t['id']}").status_code == 200
    assert client.delete(f"/api/templates/{t['id']}").status_code == 404
    assert client.get("/api/templates").json() == []
