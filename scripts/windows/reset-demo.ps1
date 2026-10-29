# Wipes demo data back to a clean state (run between demos).
# Stop the API window first, then run:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\reset-demo.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "backend")
.\.venv\Scripts\python.exe -m app.cli reset-demo
Write-Host "Demo data reset. Start the demo again with start-demo.ps1" -ForegroundColor Green
