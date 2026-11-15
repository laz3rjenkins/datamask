"""Точка входа: сервер на 127.0.0.1, случайный порт, токен доступа, открытие браузера."""

import argparse
import logging
import os
import secrets
import signal
import socket
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from datamask import __version__, security
from datamask.api import files, mask
from datamask.api.errors import install_error_handlers
from datamask.api.routes import router
from datamask.core.session import Session

HOST = "127.0.0.1"  # не настраивается: только локальная петля (SPEC §4)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
DEFAULT_MAX_UPLOAD_MB = 50
OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "DO_NOT_TRACK": "1"}


def create_app(
    token: str,
    port: int,
    session: Session,
    dist: Path = DIST,
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB,
) -> FastAPI:
    app = FastAPI(
        title="datamask", version=__version__, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.session = session
    app.state.files = {}
    app.state.max_upload_bytes = max_upload_mb * 2**20
    install_error_handlers(app)
    security.install(app, token, port)
    app.include_router(router)
    app.include_router(files.router)
    app.include_router(mask.router)
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


def bind_socket(port: int) -> socket.socket:
    # Сокет создаём сами и отдаём uvicorn: нет гонки между выбором порта и запуском.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt":
        # На Windows SO_REUSEADDR позволил бы другому процессу занять тот же порт
        sock.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
    else:
        # Иначе после перезапуска с --port N порт занят ~минуту (соединения в TIME_WAIT)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((HOST, port))
    return sock


def main() -> None:
    if sys.argv[1:2] == ["mask"]:
        from datamask.cli import mask_main

        sys.exit(mask_main(sys.argv[2:]))
    parser = argparse.ArgumentParser(
        prog="datamask", epilog="Маскирование из командной строки: datamask mask --help"
    )
    parser.add_argument("--port", type=int, default=0, help="порт (по умолчанию случайный)")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument(
        "--max-upload-mb", type=int, default=DEFAULT_MAX_UPLOAD_MB, help="лимит размера файла"
    )
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
    # Все временные файлы процесса (в т.ч. буфер загрузки multipart) — в папку сессии,
    # чтобы они удалялись вместе с ней, даже после аварийного завершения.
    tempfile.tempdir = str(session.path)
    try:
        app = create_app(token, port, session, max_upload_mb=args.max_upload_mb)
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
