"""Текстовые файлы для размаскировки: TXT, MD, HTML, JSON. Кодировка сохраняется."""

from __future__ import annotations

import json
from pathlib import Path, PurePath

from datamask.formats.base import FormatError
from datamask.formats.csv import ENCODINGS, detect_encoding
from datamask.mapping.unmask import Unmasker

TEXT_EXTENSIONS = (".txt", ".md", ".html", ".htm", ".json")


def unmask_text_file(src: Path, dest: Path, unmasker: Unmasker) -> None:
    data = src.read_bytes()
    encoding = detect_encoding(data)
    if encoding not in ENCODINGS:
        raise FormatError("Неподдерживаемая кодировка")
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as e:
        raise FormatError("Файл не читается: неизвестная кодировка") from e

    suffix = PurePath(src.name).suffix.lower()
    if suffix == ".json":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as e:
            raise FormatError("JSON не разбирается: файл повреждён") from e
        indent = 2 if "\n" in text.strip() else None
        result = json.dumps(unmasker.json_value(value), ensure_ascii=False, indent=indent)
    elif suffix in (".html", ".htm"):
        result = unmasker.html(text)
    else:
        result = unmasker.text(text)
    try:
        # newline="" — переводы строк как в исходнике
        with dest.open("w", encoding=encoding, newline="") as f:
            f.write(result)
    except UnicodeEncodeError as e:
        raise FormatError("Восстановленное значение не записывается в кодировке файла") from e
