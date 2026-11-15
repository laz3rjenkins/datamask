"""Шаблоны настроек: правила «заголовок → тип + способ». Данных из файлов не содержат."""

from __future__ import annotations

import json
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from datamask.core.models import ColumnConfig
from datamask.mapping.crypto import write_atomic
from datamask.mapping.projects import private_dir


class TemplateRule(ColumnConfig):
    header: str = Field(min_length=1, max_length=200)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    rules: list[TemplateRule] = Field(min_length=1, max_length=1000)


class Template(TemplateIn):
    id: str
    created_at: str


class TemplateRepo:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def all(self) -> list[Template]:
        if not self.path.is_file():
            return []
        return [Template.model_validate(t) for t in json.loads(self.path.read_text("utf-8"))]

    def add(self, data: TemplateIn) -> Template:
        t = Template(
            **data.model_dump(),
            id=secrets.token_hex(8),
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        with self._lock:
            self._write([*self.all(), t])
        return t

    def delete(self, template_id: str) -> bool:
        with self._lock:
            items = self.all()
            rest = [t for t in items if t.id != template_id]
            self._write(rest)
        return len(rest) != len(items)

    def _write(self, items: list[Template]) -> None:
        private_dir(self.path.parent)
        data = json.dumps([t.model_dump() for t in items], ensure_ascii=False, indent=1)
        write_atomic(self.path, data.encode("utf-8"))
