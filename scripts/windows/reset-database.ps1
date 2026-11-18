# Deletes ALL accounts, shops and requests and starts with an empty database.
# Close the "HVAC API" window first, then run:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\reset-database.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "backend")
.\.venv\Scripts\python.exe -m app.cli reset-db
if ($LASTEXITCODE -ne 0) { throw "Reset failed. Is the API window still open?" }
Write-Host "Database is empty. Start again with start-demo.ps1" -ForegroundColor Green
