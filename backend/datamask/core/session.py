"""Временная папка сессии (права 0700).

Удаляется при штатном выходе, по «Очистить сессию» (очищается) и при следующем
запуске, если прошлый процесс завершился аварийно. Живость процесса определяется
по блокировке lock-файла рядом с папкой: ОС снимает блокировку, когда процесс умирает.
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import stat
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from datamask.core.models import UserError
from datamask.core.safelog import log_exception

logger = logging.getLogger(__name__)

# Папка без lock-файла моложе этого возраста может быть ещё создаваемой другим запуском.
UNLOCKED_GRACE_SECONDS = 60.0


def default_base() -> Path:
    return Path(tempfile.gettempdir()) / "datamask"


def _lock_path(session_dir: Path) -> Path:
    return session_dir.with_name(session_dir.name + ".lock")


def _try_lock(fd: int) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _ensure_private_base(base: Path) -> None:
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        st = base.lstat()
        if stat.S_ISLNK(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise RuntimeError("Папка временных файлов datamask небезопасна (чужая или открыта)")


def _remove(session_dir: Path) -> None:
    shutil.rmtree(session_dir, ignore_errors=True)
    if session_dir.exists():
        logger.warning("Не удалось полностью удалить папку сессии")


def cleanup_stale(base: Path) -> int:
    """Удаляет папки сессий, чей процесс уже не работает. Возвращает их число."""
    removed = 0
    for entry in base.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            continue
        lock = _lock_path(entry)
        try:
            fd = os.open(lock, os.O_RDWR)
        except FileNotFoundError:
            if time.time() - entry.stat().st_mtime < UNLOCKED_GRACE_SECONDS:
                continue
            _remove(entry)
        else:
            try:
                if not _try_lock(fd):
                    continue  # процесс жив
                _remove(entry)
            finally:
                os.close(fd)
            lock.unlink(missing_ok=True)
        removed += 1
    # lock-файлы, оставшиеся без папки (сбой между удалением папки и lock-файла)
    for lock in base.glob("*.lock"):
        if lock.with_suffix("").exists():
            continue
        try:
            fd = os.open(lock, os.O_RDWR)
        except FileNotFoundError:
            continue
        try:
            free = _try_lock(fd)
        finally:
            os.close(fd)
        if free:
            lock.unlink(missing_ok=True)
    if removed:
        logger.info("Удалено папок от аварийно завершённых сессий: %d", removed)
    return removed


@dataclass
class Job:
    id: str
    folder: Path
    status: Literal["queued", "running", "done", "error"] = "queued"
    progress: int = 0
    artifacts: dict[str, Path] = field(default_factory=dict)  # вид → файл в папке задачи
    download_names: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    summary: dict[str, Any] | None = None


class Session:
    def __init__(self, path: Path, lock_fd: int) -> None:
        self.path = path
        self._lock_fd = lock_fd
        self.jobs: dict[str, Job] = {}

    def start_job(self, work: Callable[[Job], None]) -> Job:
        """Фоновая задача в отдельном потоке; ход и результат — в объекте Job."""
        job_id = secrets.token_hex(8)
        job = Job(job_id, self.path / "jobs" / job_id)
        job.folder.mkdir(parents=True)
        self.jobs[job.id] = job

        def run() -> None:
            job.status = "running"
            try:
                work(job)
            except UserError as e:
                job.error, job.status = str(e), "error"
            except Exception as e:
                log_exception(logger, e, f"Задача {job.id}")
                job.error, job.status = "Внутренняя ошибка. Подробности в журнале", "error"
            else:
                job.progress, job.status = 100, "done"
            logger.info("Задача %s: %s", job.id, job.status)

        threading.Thread(target=run, daemon=True, name=f"job-{job.id}").start()
        return job

    @classmethod
    def create(cls, base: Path | None = None) -> Session:
        base = base or default_base()
        _ensure_private_base(base)
        cleanup_stale(base)
        path = Path(tempfile.mkdtemp(dir=base))  # mkdtemp создаёт с правами 0700
        fd = os.open(_lock_path(path), os.O_RDWR | os.O_CREAT, 0o600)
        if not _try_lock(fd):
            os.close(fd)
            raise RuntimeError("Не удалось заблокировать папку сессии")
        return cls(path, fd)

    def clear(self) -> None:
        """Удаляет все файлы сессии, папка остаётся."""
        self.jobs.clear()
        for child in self.path.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

    def close(self) -> None:
        _remove(self.path)
        os.close(self._lock_fd)
        _lock_path(self.path).unlink(missing_ok=True)
