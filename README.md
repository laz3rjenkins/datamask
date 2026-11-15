# datamask

Локальный сервис маскирования персональных данных в таблицах XLSX/CSV. Работает полностью на вашем компьютере, без интернета.

## Установка и запуск

Нужны [uv](https://docs.astral.sh/uv/) и Node.js 20+.

```bash
git clone <repo> datamask && cd datamask
uv sync
scripts/run.sh          # Windows: scripts\run.ps1
```

Браузер откроется сам. Если не открылся, скопируйте ссылку с `?token=…` из терминала: без неё интерфейс не получит доступ к данным. Остановить сервер: `Ctrl+C` (временные файлы сессии удалятся).

## Командная строка

```bash
export DATAMASK_PASSWORD='пароль-для-таблицы-соответствий'   # или ввод с клавиатуры
uv run datamask mask clients.xlsx --config cfg.json --out clients_masked.xlsx \
    --mapping clients.dmmap --report report.json
```

`cfg.json` — настройки в формате `MaskConfig` (пример — в `SPEC.md`, раздел 10). Пароль
никогда не передаётся аргументом: аргументы видны в списке процессов и истории оболочки.

## Разработка

```bash
uv run pytest                                              # тесты, сеть запрещена
uv run pytest -m slow -s                                   # бенчмарк A18 (100 тыс. строк)
uv run ruff check . && uv run ruff format --check . && uv run mypy
```
