# Starts the API, the shop portal and the homeowner app, each in its own window,
# then opens both in your browser.
#   powershell -ExecutionPolicy Bypass -File scripts\windows\start-demo.ps1
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Backend = Join-Path $Root "backend"

function Open-Window($title, $dir, $command) {
  Start-Process powershell -WorkingDirectory $dir -ArgumentList @(
    "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = '$title'; $command"
  )
}

# Private keys (only created if missing), then any new database changes (keeps your data).
Set-Location $Backend
.\.venv\Scripts\python.exe -m app.cli secrets
.\.venv\Scripts\python.exe -m app.cli migrate
if ($LASTEXITCODE -ne 0) { throw "Database update failed. See the messages above." }
.\.venv\Scripts\python.exe -m app.cli check

Open-Window "HVAC API (port 8000)" $Backend ".\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
Open-Window "Shop portal (port 5173)" (Join-Path $Root "shop-portal") "npm run dev"
Open-Window "Homeowner app (port 8081)" (Join-Path $Root "mobile") "npx expo start --web --port 8081"

Write-Host "Starting... the homeowner app takes about 20 seconds to build the first time."
Start-Sleep -Seconds 8
Start-Process "http://localhost:5173"
Start-Sleep -Seconds 12
Start-Process "http://localhost:8081"
Write-Host "Shop portal:   http://localhost:5173   (create your shop account)"
Write-Host "Homeowner app: http://localhost:8081   (sign in with Google or a phone number)"
Write-Host "Technician app: http://localhost:8081/tech/sign-in   (after the shop invites them)"
Write-Host "Close the three PowerShell windows to stop everything."
