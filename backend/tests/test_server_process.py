"""Сквозные тесты на настоящем процессе: A13 (LAN), A17 (очистка при выходе и после сбоя)."""

import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="сигналы POSIX")


class Server:
    def __init__(self, tmp_path: Path) -> None:
        self.log = tmp_path / f"server-{time.monotonic_ns()}.log"
        self.base = tmp_path / "datamask"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "datamask.main", "--no-browser"],
            env={"TMPDIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
            stdout=subprocess.PIPE,
            stderr=self.log.open("w"),
            text=True,
        )
        assert self.proc.stdout is not None
        m = re.search(r"http://127\.0\.0\.1:(\d+)/\?token=(\S+)", self.proc.stdout.readline())
        assert m, "сервер не напечатал ссылку"
        self.port, self.token = int(m.group(1)), m.group(2)
        deadline = time.monotonic() + 10
        while self.status("/api/health") is None:
            assert time.monotonic() < deadline, "сервер не поднялся"
            time.sleep(0.05)

    def status(self, path: str) -> int | None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=1) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except OSError:
            return None

    def stop(self, sig: int) -> None:
        self.proc.send_signal(sig)
        self.proc.wait(timeout=10)

    def session_dirs(self) -> list[Path]:
        return [p for p in self.base.iterdir() if p.is_dir()]


LAN_PROBE = """
import socket, sys
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    u.connect(("10.255.255.255", 1))  # UDP connect ничего не отправляет, только выбирает интерфейс
    ip = u.getsockname()[0]
except OSError:
    ip = "127.0.0.1"
if ip.startswith("127."):
    print("noip")
    sys.exit()
c = socket.socket()
c.settimeout(2)
try:
    c.connect((ip, int(sys.argv[1])))
    print("open")
except OSError:
    print("closed")
"""


def test_not_reachable_via_lan_ip(tmp_path) -> None:
    server = Server(tmp_path)
    try:
        # Отдельный процесс: здесь pytest-socket сам режет не-127.0.0.1, проверка была бы пустой.
        out = subprocess.run(
            [sys.executable, "-c", LAN_PROBE, str(server.port)],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        if out == "noip":
            pytest.skip("у машины нет сетевого интерфейса кроме loopback")
        assert out == "closed"
    finally:
        server.stop(signal.SIGINT)


def test_no_token_401_and_clean_exit(tmp_path) -> None:
    server = Server(tmp_path)
    assert server.status("/api/health") == 401
    assert server.status("/") == 200
    [session_dir] = server.session_dirs()
    (session_dir / "upload.xlsx").write_bytes(b"secret")

    server.stop(signal.SIGINT)

    assert server.proc.returncode == 0  # Ctrl+C — штатный выход, без трейсбека
    assert list(server.base.iterdir()) == []
    assert server.token not in server.log.read_text()


def test_crash_leftovers_removed_on_next_start(tmp_path) -> None:
    crashed = Server(tmp_path)
    [crashed_dir] = crashed.session_dirs()
    (crashed_dir / "upload.xlsx").write_bytes(b"secret")
    crashed.stop(signal.SIGKILL)
    assert crashed_dir.exists()

    second = Server(tmp_path)
    try:
        assert not crashed_dir.exists()
        assert len(second.session_dirs()) == 1
    finally:
        second.stop(signal.SIGTERM)
    assert list(second.base.iterdir()) == []
