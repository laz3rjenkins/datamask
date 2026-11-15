"""Точка входа: сервер на 127.0.0.1, случайный свободный порт, открытие браузера."""

import argparse
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from datamask import __version__

HOST = "127.0.0.1"  # не настраивается: только локальная петля (SPEC §4)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app(dist: Path = DIST) -> FastAPI:
    app = FastAPI(
        title="datamask", version=__version__, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(prog="datamask")
    parser.add_argument("--port", type=int, default=0, help="порт (по умолчанию случайный)")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    args = parser.parse_args()

    # Сокет создаём сами и отдаём uvicorn: нет гонки между выбором порта и запуском.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((HOST, args.port))
    port = sock.getsockname()[1]
    url = f"http://{HOST}:{port}/"

    server = uvicorn.Server(uvicorn.Config(create_app(), log_level="info"))

    def open_browser() -> None:
        while not server.started:
            time.sleep(0.05)
        webbrowser.open(url)

    print(f"datamask {__version__}: {url}")
    if not args.no_browser:
        threading.Thread(target=open_browser, daemon=True).start()
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
