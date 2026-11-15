from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from datamask.core.session import Session
from datamask.main import create_app

PORT = 54321
TOKEN = "test-token-" + "x" * 32


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    s = Session.create(tmp_path / "base")
    yield s
    if s.path.exists():
        s.close()


@pytest.fixture
def make_client(session: Session, tmp_path: Path):
    def make(authed: bool = True, frontend: bool = True) -> TestClient:
        dist = tmp_path / "dist"
        dist.mkdir(exist_ok=True)
        (dist / "index.html").write_text("<html>ok</html>", encoding="utf-8")
        # без фронта, чтобы тест мог добавить свои роуты (mount на "/" перехватил бы их)
        app = create_app(TOKEN, PORT, session, dist=dist if frontend else tmp_path / "none")
        client = TestClient(app, base_url=f"http://127.0.0.1:{PORT}")
        if authed:
            client.get(f"/?token={TOKEN}")
        return client

    return make
