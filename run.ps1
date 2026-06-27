# ASHA Sahayak — one-shot setup + run (Windows PowerShell)
# Builds the frontend and starts the FastAPI server which serves both API and UI.
# Open http://localhost:8000 afterwards.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "==> Backend: creating venv + installing deps" -ForegroundColor Cyan
Set-Location "$root\backend"
if (-not (Test-Path ".venv")) { python -m venv .venv }
& ".\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt

Write-Host "==> Frontend: install + build" -ForegroundColor Cyan
Set-Location "$root\frontend"
if (-not (Test-Path "node_modules")) { npm install --no-audit --no-fund }
npm run build

Write-Host "==> Make sure Ollama is running with the model:" -ForegroundColor Yellow
Write-Host "    ollama pull llama3.2:latest"

Write-Host "==> Starting server at http://localhost:8000" -ForegroundColor Green
Set-Location "$root\backend"
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
