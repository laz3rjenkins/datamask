from fastapi.testclient import TestClient

from datamask.main import create_app


def test_health() -> None:
    r = TestClient(create_app()).get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_serves_frontend(tmp_path) -> None:
    (tmp_path / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    r = TestClient(create_app(dist=tmp_path)).get("/")
    assert r.status_code == 200
    assert "ok" in r.text
