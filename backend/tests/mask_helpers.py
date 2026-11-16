"""Общие конфиги и функции для тестов маскирования."""

import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from datamask.core.models import MaskConfig
from datamask.core.pipeline import run_mask
from datamask.formats import adapter_for
from datamask.formats.base import OpenOptions
from datamask.mapping.store import MappingStore

SECRET = b"k" * 32


def col(entity, method="pseudonym", **params):
    return {"entity": entity, "method": method, "params": params}


CLIENTS_CONFIG = {
    "categories": {"personal": True, "financial": True, "commercial": True},
    "sheets": {
        "Клиенты": {
            "header_row": 3,
            "columns": {
                "B": col("PERSON", prefix="Клиент"),
                "C": col("PHONE", "fake"),
                "D": col("EMAIL", "partial"),
                "E": col("INN_PERSON", "fake"),
                "F": col("SNILS", "hash"),
                "G": col("BIRTH_DATE", "date_shift"),
                "H": col("PASSPORT", "label"),
                "I": col("ADDRESS"),
                "K": col("FREE_TEXT"),
                "L": col("PERSON"),
            },
        },
        "Продажи": {
            "header_row": 1,
            "columns": {"B": col("PERSON"), "C": col("PERSON"), "D": col("AMOUNT", "scale")},
        },
        "Архив": {
            "header_row": 1,
            "columns": {
                "A": col("PERSON"),
                "B": col("PHONE", "fake"),
                "C": col("BIRTH_DATE", "date_shift"),
            },
        },
    },
    "custom_terms": ["отдел продаж"],
}


def run(src: Path, out: Path, config: dict, store: MappingStore | None = None):
    adapter = adapter_for(src.name)
    doc = adapter.open(src, OpenOptions())
    store = store or MappingStore(SECRET)
    result = run_mask(adapter, doc, MaskConfig.model_validate(config), store, out)
    return result, store


def zip_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        return "\n".join(
            z.read(n).decode("utf-8", "replace") for n in z.namelist() if not n.endswith(".png")
        )


def leaks(text: str, values) -> list[str]:
    """Значения, найденные в тексте как есть или в XML-экранировании."""
    return sorted({v for v in values if v and (v in text or escape(v, {'"': "&quot;"}) in text)})


def soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def soffice_opens(path: Path, outdir: Path) -> bool:
    exe = soffice()
    assert exe
    r = subprocess.run(
        [exe, "--headless", "--convert-to", "csv", "--outdir", str(outdir), str(path)],
        capture_output=True,
        timeout=120,
    )
    return r.returncode == 0 and any(outdir.glob("*.csv"))
