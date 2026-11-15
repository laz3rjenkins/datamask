"""A13 (через TestClient), заголовки, токен, ошибки без данных."""

import logging

from conftest import PORT, TOKEN

from datamask.main import bind_socket
from datamask.security import cookie_name


def test_binds_loopback_only() -> None:
    sock = bind_socket(0)
    try:
        assert sock.getsockname()[0] == "127.0.0.1"
    finally:
        sock.close()


def test_api_without_token_is_401(make_client) -> None:
    client = make_client(authed=False)
    for method, path in [("GET", "/api/health"), ("DELETE", "/api/session"), ("GET", "/api/x")]:
        r = client.request(method, path)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthorized"


def test_wrong_cookie_is_401(make_client) -> None:
    client = make_client(authed=False)
    client.cookies.set(cookie_name(PORT), TOKEN + "x")
    assert client.get("/api/health").status_code == 401


def test_token_exchange_sets_strict_httponly_cookie_and_strips_url(make_client) -> None:
    client = make_client(authed=False)
    r = client.get(f"/?token={TOKEN}", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    set_cookie = r.headers["set-cookie"].lower()
    assert set_cookie.startswith(cookie_name(PORT) + "=")
    assert "httponly" in set_cookie
    assert "samesite=strict" in set_cookie
    assert client.get("/api/health").json()["status"] == "ok"


def test_wrong_token_sets_no_cookie(make_client) -> None:
    client = make_client(authed=False)
    r = client.get("//evil.example/?token=nope", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert "set-cookie" not in r.headers


def test_foreign_host_is_400(make_client) -> None:
    client = make_client()
    for host in ["evil.example", f"evil.example:{PORT}", "127.0.0.1:1", "localhost", ""]:
        r = client.get("/api/health", headers={"host": host})
        assert r.status_code == 400, host
        assert r.json()["error"]["code"] == "bad_host"
    assert client.get("/api/health", headers={"host": f"localhost:{PORT}"}).status_code == 200


def test_csp_on_all_responses_and_no_cors(make_client) -> None:
    client = make_client()
    unauth = make_client(authed=False)
    responses = [
        client.get("/"),
        client.get("/api/health"),
        client.get("/api/nope"),
        unauth.get("/api/health"),
        client.get("/api/health", headers={"host": "evil.example"}),
        client.options(
            "/api/health",
            headers={"origin": "http://evil.example", "access-control-request-method": "GET"},
        ),
        client.get("/api/health", headers={"origin": "http://evil.example"}),
    ]
    for r in responses:
        assert r.headers["content-security-policy"] == (
            "default-src 'self'; connect-src 'self'; img-src 'self' data:"
        )
        assert not [h for h in r.headers if h.lower().startswith("access-control-")]


def test_unknown_api_route_uses_error_format(make_client) -> None:
    r = make_client().get("/api/nope")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "not_found", "message": "Не найдено"}}


def test_exception_logged_without_values(make_client, caplog) -> None:
    client = make_client(frontend=False)
    marker = "ЗАМЕТКА_7f3a_Иванов"

    @client.app.get("/api/boom")
    def boom() -> None:
        raise ValueError(f"плохое значение {marker}")

    with caplog.at_level(logging.INFO):
        r = client.get(f"/api/boom?q={marker}")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal"
    assert marker not in r.text
    assert "ValueError" in caplog.text
    assert marker not in caplog.text
    assert TOKEN not in caplog.text


def test_validation_error_does_not_echo_input(make_client) -> None:
    client = make_client(frontend=False)
    marker = "ЗАМЕТКА_7f3a_Петров"

    @client.app.get("/api/num")
    def num(n: int) -> int:
        return n

    r = client.get("/api/num", params={"n": marker})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert marker not in r.text


def test_clear_session_endpoint_empties_folder(make_client, session) -> None:
    (session.path / "upload.xlsx").write_bytes(b"data")
    (session.path / "job").mkdir()
    (session.path / "job" / "out.csv").write_text("x")
    r = make_client().delete("/api/session")
    assert r.status_code == 200
    assert session.path.is_dir()
    assert list(session.path.iterdir()) == []
