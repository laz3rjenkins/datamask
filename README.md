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

## Разработка

```bash
uv run pytest                                              # тесты, сеть запрещена
uv run ruff check . && uv run ruff format --check . && uv run mypy
```
