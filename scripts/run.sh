#!/usr/bin/env bash
# Сборка фронта (если нет dist или исходники новее) и запуск сервера.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html -newer frontend/dist/index.html 2>/dev/null)" ]; then
  (cd frontend && { [ -d node_modules ] || npm ci; } && npm run build)
fi
exec uv run datamask "$@"
