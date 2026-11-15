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
cd frontend && npm test && npm run lint                    # тесты и линтер интерфейса
```

## Файлы для ручной проверки

Синтетические таблицы (Faker `ru_RU`, реальных данных нет) создаются командой
`uv run python scripts/make_fixtures.py` в папке `backend/tests/fixtures/` (её нет в git):

- `clients.xlsx` — «грязная» книга: шапка отчёта над заголовком, скрытый лист и колонка,
  примечания, сводная с кэшем, картинка, формулы, свободный текст с телефонами;
- `clients_cp1251.csv` — CSV в Windows-1251 с `;`, коды с ведущими нулями (`007`);
- `clients_utf8.csv` — CSV в UTF-8 с BOM;
- `labeled/` — 20 размеченных таблиц для проверки подсказок (A4).
