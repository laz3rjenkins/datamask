# Сборка фронта (если нет dist) и запуск сервера.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path "frontend/dist/index.html")) {
    Push-Location frontend
    if (-not (Test-Path "node_modules")) { npm ci }
    npm run build
    Pop-Location
}
uv run datamask @args
