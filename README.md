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

Файлы до 1 ГБ (`scripts/run.sh --max-upload-mb 2048` — больше). Книга на 200 МБ и 40 листов
маскируется за несколько минут; память при этом не растёт с размером листов.

## Командная строка

```bash
export DATAMASK_PASSWORD='пароль-для-таблицы-соответствий'   # или ввод с клавиатуры
uv run datamask mask clients.xlsx --config cfg.json --out clients_masked.xlsx \
    --mapping clients.dmmap --report report.json
```

`cfg.json` — настройки в формате `MaskConfig` (пример — в `SPEC.md`, раздел 10). Пароль
никогда не передаётся аргументом: аргументы видны в списке процессов и истории оболочки.

Вернуть настоящие значения в файл, сделанный по замаскированным данным (XLSX, CSV, TXT, MD,
HTML, JSON):

```bash
uv run datamask unmask dashboard.html --mapping clients.dmmap --out dashboard_real.html
```

## Где хранятся данные

- Временные файлы сессии — во временной папке с правами `0700`, удаляются при выходе.
- Проекты и шаблоны — в папке данных приложения: `~/Library/Application Support/datamask`
  (macOS), `%APPDATA%\datamask` (Windows), `~/.local/share/datamask` (Linux). Таблицы
  соответствий проектов зашифрованы паролем проекта; открыто лежат только названия проектов,
  даты и число записей.

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

Большая книга для замеров: `uv run python scripts/make_fixtures.py --big 200 big.xlsx`
(~200 МБ, 40 листов, строки в sharedStrings, как у Excel).
