"""Защита локального сервера (SPEC §4 «Сеть»): Host, токен → cookie, заголовки, логи без данных."""

import logging
import secrets
import traceback
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse

from datamask.api.errors import error_response

logger = logging.getLogger("datamask.http")

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; connect-src 'self'; img-src 'self' data:",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",  # ответы с данными не должны оседать в кеше браузера
}


def cookie_name(port: int) -> str:
    # Cookie не разделяются по портам: у каждого запуска своё имя, чтобы не затирать друг друга.
    return f"datamask_{port}"


def log_exception(exc: BaseException) -> None:
    """Тип исключения и место, без сообщения: в нём бывают значения ячеек."""
    frames = traceback.extract_tb(exc.__traceback__)[-6:]
    where = " <- ".join(f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in reversed(frames))
    logger.error("Необработанное исключение %s в %s", type(exc).__name__, where)


def install(app: FastAPI, token: str, port: int) -> None:
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    token_bytes = token.encode()
    cookie = cookie_name(port)

    def token_ok(candidate: str) -> bool:
        return secrets.compare_digest(candidate.encode(), token_bytes)

    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.headers.get("host", "").lower() not in allowed_hosts:
            return error_response(400, "bad_host", "Недопустимый заголовок Host")
        path = request.url.path
        if path == "/api" or path.startswith("/api/"):
            if not token_ok(request.cookies.get(cookie, "")):
                return error_response(
                    401,
                    "unauthorized",
                    "Нет доступа. Откройте ссылку из окна запуска datamask",
                )
        elif "token" in request.query_params:
            # Всегда на "/", а не на исходный путь: "//чужой.сайт" дал бы открытый редирект.
            response: Response = RedirectResponse("/", status_code=303)
            if token_ok(request.query_params["token"]):
                response.set_cookie(cookie, token, httponly=True, samesite="strict", path="/")
            return response
        try:
            return await call_next(request)
        except Exception as exc:
            log_exception(exc)
            return error_response(500, "internal", "Внутренняя ошибка. Подробности в журнале")

    @app.middleware("http")
    async def security_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await guard(request, call_next)
        response.headers.update(SECURITY_HEADERS)
        # Путь без query (там бывает токен); %r экранирует переводы строк.
        logger.info("%s %r -> %d", request.method, request.url.path, response.status_code)
        return response
