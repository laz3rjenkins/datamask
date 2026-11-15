"""A18: 100 тыс. строк × 10 колонок (5 маскируемых) ≤ 60 с, предпросмотр ≤ 3 с.

Не в каждом прогоне: uv run pytest -m slow"""

import time

import pytest
from mask_helpers import col, run
from openpyxl import Workbook

from datamask.formats.base import OpenOptions
from datamask.formats.xlsx import XlsxAdapter

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
