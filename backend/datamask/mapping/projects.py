"""Проекты: одна таблица соответствий на несколько файлов клиента (SPEC §6, экран 6; §9).

<папка данных>/projects/<id>.dmmap — таблица в формате .dmmap (вместе с секретом проекта и своим
словарём), зашифрована паролем проекта. <id>.json — то, что показывается в списке без пароля:
название, даты, число записей. Значений и словаря там нет."""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from datamask.core.models import UserError
from datamask.mapping.crypto import MIN_PASSWORD, write_atomic
from datamask.mapping.store import MappingStore

_ID = re.compile(r"[0-9a-f]{16}")


class ProjectError(UserError):
    pass


@dataclass(frozen=True)
class ProjectMeta:
    id: str
    name: str
    created_at: str
    updated_at: str
    entries: int


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


class ProjectRepo:
    def __init__(self, root: Path) -> None:
        self.root = root
        # ponytail: один замок на все проекты; задачи маскирования короткие, а запись проекта
        # должна быть «прочитал → дополнил → записал» без гонок. Замок на проект — если упрёмся.
        self.lock = threading.Lock()

    def _paths(self, project_id: str) -> tuple[Path, Path]:
        if not _ID.fullmatch(project_id):
            raise ProjectError("Проект не найден")
        return self.root / f"{project_id}.json", self.root / f"{project_id}.dmmap"

    def all(self) -> list[ProjectMeta]:
        if not self.root.is_dir():
            return []
        out = []
        for f in self.root.glob("*.json"):
            try:
                out.append(ProjectMeta(**json.loads(f.read_text("utf-8"))))
            except (ValueError, TypeError):
                continue  # битый файл описания не должен ронять список
        return sorted(out, key=lambda p: p.updated_at, reverse=True)

    def get(self, project_id: str) -> ProjectMeta:
        meta, data = self._paths(project_id)
        if not (meta.is_file() and data.is_file()):
            raise ProjectError("Проект не найден")
        return ProjectMeta(**json.loads(meta.read_text("utf-8")))

    def create(self, name: str, password: str) -> ProjectMeta:
        name = " ".join(name.split())
        if not 1 <= len(name) <= 100:
            raise ProjectError("Название проекта — от 1 до 100 символов")
        if len(password) < MIN_PASSWORD:
            raise ProjectError(f"Пароль проекта — не короче {MIN_PASSWORD} символов")
        with self.lock:
            if any(p.name.lower() == name.lower() for p in self.all()):
                raise ProjectError("Проект с таким названием уже есть")
            project_id = secrets.token_hex(8)
            store = MappingStore(secrets.token_bytes(32), project_id)
            now = _now()
            meta = ProjectMeta(project_id, name, now, now, 0)
            self._write(meta, store, password)
            return meta

    def delete(self, project_id: str) -> None:
        self.get(project_id)
        with self.lock:
            for p in self._paths(project_id):
                p.unlink(missing_ok=True)

    def load(self, project_id: str, password: str) -> MappingStore:
        """MappingError при неверном пароле."""
        self.get(project_id)
        return MappingStore.decrypt(self._paths(project_id)[1].read_bytes(), password)

    def save(self, project_id: str, store: MappingStore, password: str) -> ProjectMeta:
        """Вызывать под self.lock вместе с load: иначе параллельная задача затрёт записи."""
        old = self.get(project_id)
        meta = ProjectMeta(project_id, old.name, old.created_at, _now(), len(store.entries))
        self._write(meta, store, password)
        return meta

    def _write(self, meta: ProjectMeta, store: MappingStore, password: str) -> None:
        private_dir(self.root)
        meta_path, data_path = self._paths(meta.id)
        # Сначала данные, потом описание: сбой между ними оставит верную таблицу.
        write_atomic(data_path, store.encrypt(password, include_secret=True))
        write_atomic(meta_path, json.dumps(asdict(meta), ensure_ascii=False).encode("utf-8"))
