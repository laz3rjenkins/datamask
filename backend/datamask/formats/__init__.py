from pathlib import PurePath

from datamask.formats.base import FormatAdapter, FormatError
from datamask.formats.csv import CsvAdapter
from datamask.formats.xlsx import XlsxAdapter

ADAPTERS: tuple[FormatAdapter, ...] = (XlsxAdapter(), CsvAdapter())

_REJECTED = {
    ".xls": "Старый формат .xls не поддерживается. Пересохраните файл в Excel как .xlsx",
    ".xlsm": "Файлы с макросами (.xlsm) не поддерживаются. Сохраните книгу как .xlsx",
}


def adapter_for(filename: str) -> FormatAdapter:
    suffix = PurePath(filename).suffix.lower()
    for adapter in ADAPTERS:
        if suffix in adapter.extensions:
            return adapter
    raise FormatError(_REJECTED.get(suffix, "Поддерживаются только файлы .xlsx и .csv"))
