"""Точка входа: сервер на 127.0.0.1, случайный порт, токен доступа, открытие браузера."""

import argparse
import logging
import os
import secrets
import signal
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from datamask import __version__, security
from datamask.api.errors import install_error_handlers
from datamask.api.routes import router
from datamask.core.session import Session

HOST = "127.0.0.1"  # не настраивается: только локальная петля (SPEC §4)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "DO_NOT_TRACK": "1"}


def create_app(token: str, port: int, session: Session, dist: Path = DIST) -> FastAPI:
    app = FastAPI(
        title="datamask", version=__version__, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.session = session
    install_error_handlers(app)
    security.install(app, token, port)
    app.include_router(router)
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def bind_socket(port: int) -> socket.socket:
    # Сокет создаём сами и отдаём uvicorn: нет гонки между выбором порта и запуском.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((HOST, port))
    return sock


def main() -> None:
    parser = argparse.ArgumentParser(prog="datamask")
    parser.add_argument("--port", type=int, default=0, help="порт (по умолчанию случайный)")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    args = parser.parse_args()

    os.environ.update(OFFLINE_ENV)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    sock = bind_socket(args.port)
    port = sock.getsockname()[1]
    token = secrets.token_urlsafe(32)
    url = f"http://{HOST}:{port}/?token={token}"
    session = Session.create()
    try:
        app = create_app(token, port, session)
        # access_log выключен: uvicorn пишет путь с query, а там токен. Свой лог — в security.
        server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))

        def open_browser() -> None:
            while not server.started:
                time.sleep(0.05)
            webbrowser.open(url)

        print(f"datamask {__version__}: {url}", flush=True)
        if not args.no_browser:
            threading.Thread(target=open_browser, daemon=True).start()
        # uvicorn после остановки повторно посылает себе пойманный сигнал. С обработчиком
        # SIGTERM по умолчанию процесс умер бы до finally и оставил файлы сессии.
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(128 + signal.SIGTERM))
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        pass  # Ctrl+C — штатный выход
    finally:
        session.close()


if __name__ == "__main__":
    main()
