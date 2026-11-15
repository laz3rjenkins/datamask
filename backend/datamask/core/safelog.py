"""Логирование исключений без сообщений: в тексте исключения бывают значения ячеек."""

from __future__ import annotations

import logging
import traceback
from pathlib import Path


def log_exception(logger: logging.Logger, exc: BaseException, what: str) -> None:
    frames = traceback.extract_tb(exc.__traceback__)[-6:]
    where = " <- ".join(f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in reversed(frames))
    logger.error("%s: исключение %s в %s", what, type(exc).__name__, where)
