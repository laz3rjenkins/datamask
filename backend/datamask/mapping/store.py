"""Таблица соответствий. Ведётся по типу данных, а не по колонке (SPEC §9)."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from datamask.core.models import EntityType
from datamask.core.normalize import normalize
from datamask.mapping.crypto import MIN_PASSWORD, MappingError, decrypt, encrypt

VERSION = 1


@dataclass(frozen=True)
class Entry:
    entity: str
    original: str
    masked: str
    method: str


# тип, способ (pseudonym, fake, hash), нормализованное значение
Key = tuple[EntityType, str, str]


class MappingStore:
    def __init__(self, secret: bytes, project: str | None = None) -> None:
        self.secret = secret  # для фейков, хешей и параметров сдвига/масштаба; не сериализуется
        self.project = project
        self.entries: list[Entry] = []
        self._by_key: dict[Key, str] = {}
        # masked → ключ: псевдоним однозначно указывает на исходник
        self._owner: dict[str, Key] = {}
        self._counters: dict[str, int] = {}
        # область («Лист!B» или «*») → {"days"/"factor": …, "columns": [{sheet, column, header,
        # header_row}]}: по колонкам даты и числа восстанавливаются при размаскировке
        self.date_shifts: dict[str, dict[str, Any]] = {}
        self.scale_factors: dict[str, dict[str, Any]] = {}
        self.custom_terms: list[str] = []  # свой словарь проекта

    # ---- значения ----

    def get(self, key: Key) -> str | None:
        return self._by_key.get(key)

    def owner(self, masked: str) -> Key | None:
        return self._owner.get(masked)

    def add(self, key: Key, original: str, masked: str, method: str) -> None:
        if masked in self._owner and self._owner[masked] != key:
            raise ValueError("masked value already taken")
        self._by_key[key] = masked
        self._owner[masked] = key
        self.entries.append(Entry(key[0].value, original, masked, method))

    def next_number(self, prefix: str) -> int:
        n = self._counters.get(prefix, 0) + 1
        while f"{prefix}_{n:04d}" in self._owner:
            n += 1
        self._counters[prefix] = n
        return n

    # ---- параметры колонок: одно случайное значение на колонку или файл ----

    def _derive(self, label: str, scope: str) -> int:
        digest = hmac.new(self.secret, f"{label}:{scope}".encode(), hashlib.sha256).digest()
        return int.from_bytes(digest[:8], "big")

    @staticmethod
    def _param(
        table: dict[str, dict[str, Any]], scope: str, name: str, value: Any, info: dict[str, str]
    ) -> Any:
        item = table.setdefault(scope, {name: value, "columns": []})
        if info and info not in item["columns"]:
            item["columns"].append(info)
        return item[name]

    def date_shift(self, scope: str, info: dict[str, str]) -> int:
        v = self._derive("shift", scope) % 730
        days = v - 365 if v < 365 else v - 364  # ±1..365, без нуля
        return int(self._param(self.date_shifts, scope, "days", days, info))

    def scale_factor(self, scope: str, info: dict[str, str]) -> float:
        factor = 0.5 + (self._derive("scale", scope) % 15001) / 10000  # 0,5–2,0
        return float(self._param(self.scale_factors, scope, "factor", factor, info))

    # ---- сериализация ----

    def to_json(self, include_secret: bool = False) -> bytes:
        """include_secret — только для файла проекта: секрет нужен, чтобы фейки, хеши и сдвиги
        в следующих файлах проекта совпали. В выгружаемый .dmmap секрет не попадает."""
        data: dict[str, Any] = {
            "version": VERSION,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "project": self.project,
            "entries": [asdict(e) for e in self.entries],
            "date_shifts": self.date_shifts,
            "scale_factors": self.scale_factors,
            "custom_terms": self.custom_terms,
        }
        if include_secret:
            data["secret"] = self.secret.hex()
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    def encrypt(self, password: str, include_secret: bool = False) -> bytes:
        if len(password) < MIN_PASSWORD:
            raise MappingError(f"Пароль должен быть не короче {MIN_PASSWORD} символов")
        return encrypt(self.to_json(include_secret), password)

    @classmethod
    def from_json(cls, data: bytes, secret: bytes = b"") -> MappingStore:
        raw = json.loads(data)
        if raw.get("version") != VERSION:
            raise MappingError("Неподдерживаемая версия таблицы соответствий")
        store = cls(secret or bytes.fromhex(raw.get("secret", "")), raw.get("project"))
        for e in raw["entries"]:
            entity = EntityType(e["entity"])
            masked = e["masked"]
            m = re.fullmatch(r"(.+)_(\d{4,})", masked)
            if e["method"] == "pseudonym" and m:  # нумерация продолжается с известных
                store._counters[m[1]] = max(store._counters.get(m[1], 0), int(m[2]))
            key = (entity, e["method"], normalize(entity, e["original"]))
            store.add(key, e["original"], masked, e["method"])
        store.date_shifts = raw.get("date_shifts", {})
        store.scale_factors = raw.get("scale_factors", {})
        store.custom_terms = list(raw.get("custom_terms", []))
        return store

    @classmethod
    def decrypt(cls, blob: bytes, password: str, secret: bytes = b"") -> MappingStore:
        plain = decrypt(blob, password)
        try:
            return cls.from_json(plain, secret)
        except (ValueError, KeyError, TypeError) as e:
            raise MappingError("Неверный пароль или файл повреждён") from e
