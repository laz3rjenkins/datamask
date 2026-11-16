"""A18: 100 тыс. строк × 10 колонок (5 маскируемых) ≤ 60 с, предпросмотр ≤ 3 с; книга ~200 МБ.

Не в каждом прогоне: uv run pytest -m slow -s"""

import os
import resource
import sys
import time

import make_fixtures
import pytest
from mask_helpers import col, run
from openpyxl import Workbook

from datamask.core.models import MaskConfig
from datamask.core.pipeline import run_mask, sample_sheet
from datamask.formats.base import OpenOptions
from datamask.formats.xlsx import XlsxAdapter
from datamask.mapping.store import MappingStore

pytestmark = pytest.mark.slow


def test_a18_benchmark(tmp_path) -> None:
    src = tmp_path / "big.xlsx"
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Данные")
    ws.append(["ФИО", "Телефон", "Email", "Сумма", "Комментарий", "f", "g", "h", "i", "j"])
    for r in range(100_000):
        ws.append(
            [f"Иванов Иван {r % 5000}", f"+7912{r:07d}", f"user{r % 7000}@mail.ru", r * 1.5,
             f"Перезвонить по +7 912 {r % 1000:03d}-00-00 после обеда", r, "a", "b", "c", "d"]
        )  # fmt: skip
    wb.save(src)

    adapter = XlsxAdapter()
    t = time.perf_counter()
    doc = adapter.open(src, OpenOptions())
    adapter.preview(doc, "Данные", None, 200)
    preview = time.perf_counter() - t

    config = {
        "categories": {"commercial": True},
        "sheets": {
            "Данные": {
                "columns": {
                    "A": col("PERSON"),
                    "B": col("PHONE", "fake"),
                    "C": col("EMAIL", "hash"),
                    "D": col("AMOUNT", "scale"),
                    "E": col("FREE_TEXT"),
                }
            }
        },
    }
    t = time.perf_counter()
    run(src, tmp_path / "out.xlsx", config)
    total = time.perf_counter() - t
    print(f"\nпредпросмотр {preview:.1f} с, маскирование {total:.1f} с")
    assert preview <= 3
    assert total <= 60


BIG_COLUMNS = {
    "B": col("PERSON"),
    "C": col("PHONE", "fake"),
    "D": col("EMAIL", "hash"),
    "E": col("INN_PERSON"),
    "F": col("SNILS"),
    "G": col("BIRTH_DATE", "date_shift"),
    "H": col("ADDRESS"),
    "J": col("AMOUNT", "scale"),
    "M": col("FREE_TEXT"),
}


def _peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 2**20 if sys.platform == "darwin" else peak / 2**10  # macOS — байты, Linux — КБ


def test_big_book(tmp_path) -> None:
    """Книга ~200 МБ, 40 листов (DATAMASK_BENCH_MB — другой размер). Память не должна расти с
    размером листов: на этом файле полная загрузка в openpyxl требовала бы ~23 ГБ."""
    size = float(os.environ.get("DATAMASK_BENCH_MB", "200"))
    src = make_fixtures.write_big_xlsx(tmp_path / "big.xlsx", size)
    adapter = XlsxAdapter()
    doc = adapter.open(src, OpenOptions())
    names = [s.name for s in doc.sheets]
    t = time.perf_counter()
    for name in names:
        sample_sheet(adapter, doc, name, None)
    suggest = time.perf_counter() - t

    config = MaskConfig.model_validate(
        {"categories": {"commercial": True}, "sheets": {n: {"columns": BIG_COLUMNS} for n in names}}
    )
    t = time.perf_counter()
    result = run_mask(adapter, doc, config, MappingStore(b"k" * 32), tmp_path / "out.xlsx")
    total = time.perf_counter() - t
    replaced = sum(c.replaced for c in result.columns)
    print(
        f"\n{src.stat().st_size / 2**20:.0f} МБ, листов {len(names)}: подсказки {suggest:.1f} с, "
        f"маскирование {total:.0f} с, заменено {replaced}, пик памяти {_peak_rss_mb():.0f} МБ"
    )
    assert suggest <= 30  # первые scan_rows строк каждого листа, не весь файл
    assert _peak_rss_mb() <= 3000
