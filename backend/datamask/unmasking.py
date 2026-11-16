"""Размаскировка файла целиком: выбор обхода по формату + отчёт без данных."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Any

from datamask import __version__
from datamask.core.pipeline import run_unmask_table
from datamask.formats import adapter_for
from datamask.formats.base import FormatError, OpenOptions
from datamask.formats.text import TEXT_EXTENSIONS, unmask_text_file
from datamask.mapping.store import MappingStore
from datamask.mapping.unmask import Unmasker

UNMASK_EXTENSIONS = (".xlsx", ".csv", *TEXT_EXTENSIONS)
TABLE_NOTE = "Даты и числа восстанавливаются только в XLSX/CSV, в тех же колонках (по заголовку)"
TEXT_NOTE = (
    "В тексте даты и суммы не восстанавливаются: нельзя надёжно понять, какое число было "
    "замаскировано. Исходные значения — в исходном файле"
)


def unmask_file(src: Path, dest: Path, store: MappingStore) -> dict[str, Any]:
    suffix = PurePath(src.name).suffix.lower()
    if suffix not in UNMASK_EXTENSIONS:
        raise FormatError("Размаскировать можно файлы XLSX, CSV, TXT, MD, HTML и JSON")
    unmasker = Unmasker(store)
    if suffix in TEXT_EXTENSIONS:
        unmask_text_file(src, dest, unmasker)
    else:
        adapter = adapter_for(src.name)
        run_unmask_table(adapter, adapter.open(src, OpenOptions()), unmasker, dest)
    notes = [TABLE_NOTE]
    if suffix in TEXT_EXTENSIONS and (store.date_shifts or store.scale_factors):
        notes.append(TEXT_NOTE)
    if unmasker.stats.unknown:
        notes.append(
            "Часть токенов не найдена в таблице соответствий и осталась как есть: возможно, "
            "файл маскировался с другой таблицей или проектом"
        )
    return {
        "tool": f"datamask {__version__}",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "format": suffix.lstrip("."),
        **unmasker.stats.report(),
        "notes": notes,
    }
