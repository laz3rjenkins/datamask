"""Эндпоинты dry-run/mask/jobs/download и A14: в логах, отчётах и ошибках нет исходных данных."""

import io
import json
import logging
import time
from urllib.parse import quote

from mask_helpers import CLIENTS_CONFIG, col
from openpyxl import Workbook, load_workbook
from test_files_api import upload

from datamask.mapping.store import MappingStore

PASSWORD = "очень-длинный-пароль"


def wait(client, job_id, timeout=30.0):
    deadline = time.monotonic() + timeout
    while True:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        assert time.monotonic() < deadline, job
        time.sleep(0.05)


def test_dry_run_endpoint(make_client, fixtures) -> None:
    client = make_client()
    file_id = upload(client, fixtures / "clients.xlsx").json()["file_id"]
    r = client.post(f"/api/files/{file_id}/dry-run", json=CLIENTS_CONFIG)
    assert r.status_code == 200, r.text
    body = r.json()
    sheet = next(s for s in body["sheets"] if s["sheet"] == "Клиенты")
    row = next(r for r in sheet["rows"] if r["row"] == 4)
    assert row["after"][1] == "Клиент_0001" and row["changed"][1]
    assert next(c for c in sheet["columns"] if c["key"] == "H")["reversible"] is False
    assert any("свободного текста" in w for w in body["warnings"])
    assert {s["key"] for s in body["summary"] if s["sheet"] == "Клиенты"} >= {"B", "C", "L"}


def test_invalid_config_and_password(make_client, fixtures) -> None:
    client = make_client()
    file_id = upload(client, fixtures / "clients.xlsx").json()["file_id"]
    bad = {"sheets": {"Клиенты": {"columns": {"D": col("EMAIL", "date_shift")}}}}
    for path, body in [("dry-run", bad), ("mask", {"config": bad, "password": PASSWORD})]:
        r = client.post(f"/api/files/{file_id}/{path}", json=body)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "invalid_config"
        assert "Сдвиг дат" in r.json()["error"]["message"]
    r = client.post(
        f"/api/files/{file_id}/mask", json={"config": CLIENTS_CONFIG, "password": "short"}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "weak_password"
    r = client.post(
        f"/api/files/{file_id}/mask", json={"config": {**CLIENTS_CONFIG, "save_mapping": False}}
    )
    assert r.status_code == 200


def test_mask_job_and_downloads(make_client, fixtures, session) -> None:
    client = make_client()
    file_id = upload(client, fixtures / "clients.xlsx", "Клиенты Q3.xlsx").json()["file_id"]
    r = client.post(
        f"/api/files/{file_id}/mask", json={"config": CLIENTS_CONFIG, "password": PASSWORD}
    )
    job = wait(client, r.json()["job_id"])
    assert job["status"] == "done", job
    assert set(job["artifacts"]) == {"masked", "mapping", "report_json", "report_html"}
    assert job["summary"]["by_entity"]["PERSON"]["replaced"] > 0

    base = f"/api/jobs/{job['job_id']}/download"
    masked = client.get(f"{base}/masked")
    assert masked.status_code == 200
    assert quote("Клиенты Q3_masked.xlsx") in masked.headers["content-disposition"]
    mapping = client.get(f"{base}/mapping")
    store = MappingStore.decrypt(mapping.content, PASSWORD)
    assert any(e.masked == "Клиент_0001" for e in store.entries)
    report = client.get(f"{base}/report_json").json()
    assert report["file_id"] == file_id and report["mapping_saved"] is True
    assert "<table>" in client.get(f"{base}/report_html").text
    assert client.get(f"{base}/nope").status_code == 404
    assert client.get("/api/jobs/deadbeef").status_code == 404

    # результаты лежат в папке сессии и удаляются «Очистить сессию»
    assert list((session.path / "jobs").rglob("mapping.dmmap"))
    client.delete("/api/session")
    assert client.get(f"/api/jobs/{job['job_id']}").status_code == 404
    assert list(session.path.iterdir()) == []


def test_mask_csv_job(make_client, fixtures) -> None:
    client = make_client()
    file_id = upload(client, fixtures / "clients_cp1251.csv").json()["file_id"]
    client.patch(f"/api/files/{file_id}", json={"delimiter": ";"})
    config = {"sheets": {"CSV": {"columns": {"2": col("PERSON")}}}, "save_mapping": False}
    job = wait(
        client, client.post(f"/api/files/{file_id}/mask", json={"config": config}).json()["job_id"]
    )
    assert job["status"] == "done" and "mapping" not in job["artifacts"]
    text = client.get(f"/api/jobs/{job['job_id']}/download/masked").content.decode("cp1251")
    assert text.splitlines()[1].split(";")[1] == "Персона_0001"


MARKER = "ЗАМЕТКА_7f3a9c"


def test_a14_no_values_in_logs_reports_errors(make_client, tmp_path, caplog) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Лист1"
    ws.append(["ФИО", "Телефон", "Комментарий"])
    for i in range(20):
        ws.append(
            [
                f"{MARKER}ов Иван Петрович{i}",
                f"+7 912 000-00-{i:02d}",
                f"{MARKER} перезвонить по +7 912 111-11-{i:02d}, без деталей и подробностей",
            ]
        )
    src = tmp_path / "src.xlsx"
    wb.save(src)
    client = make_client()
    config = {
        "sheets": {
            "Лист1": {
                "columns": {"A": col("PERSON"), "B": col("PHONE", "fake"), "C": col("FREE_TEXT")}
            }
        }
    }
    with caplog.at_level(logging.DEBUG):
        r = upload(client, src, f"Договор_{MARKER}.xlsx")
        file_id = r.json()["file_id"]
        texts = [r.text]
        # предпросмотр, подсказки и «до/после» показывают данные в интерфейсе по назначению;
        # здесь важно, что их вызовы не пишут значения в лог
        client.get(f"/api/files/{file_id}/sheets/{quote('Лист1')}/preview")
        client.post(f"/api/files/{file_id}/suggest", json={})
        client.post(f"/api/files/{file_id}/dry-run", json=config)
        bad = {"sheets": {"Лист1": {"columns": {"A": col("PERSON", "scale")}}}}
        texts.append(
            client.post(
                f"/api/files/{file_id}/mask", json={"config": bad, "password": PASSWORD}
            ).text
        )
        job = wait(
            client,
            client.post(
                f"/api/files/{file_id}/mask", json={"config": config, "password": PASSWORD}
            ).json()["job_id"],
        )
        base = f"/api/jobs/{job['job_id']}/download"
        texts += [client.get(f"/api/jobs/{job['job_id']}").text]
        texts += [client.get(f"{base}/report_json").text, client.get(f"{base}/report_html").text]
        masked = load_workbook(io.BytesIO(client.get(f"{base}/masked").content))
    assert job["status"] == "done"
    assert masked["Лист1"]["A2"].value == "Персона_0001"
    for t in texts:
        assert MARKER not in t
        assert "Петрович" not in t and "912" not in t
    assert MARKER not in caplog.text and "Петрович" not in caplog.text and "912" not in caplog.text
    assert PASSWORD not in caplog.text
    report = json.loads(texts[-2])
    assert report["columns"][0]["header"] == "ФИО"  # имена колонок в отчёте можно
