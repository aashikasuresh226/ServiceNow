# Starts the API, the shop portal and the homeowner app, each in its own window,
# then opens both in your browser.
#   powershell -ExecutionPolicy Bypass -File scripts\windows\start-demo.ps1
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

function Open-Window($title, $dir, $command) {
  Start-Process powershell -WorkingDirectory $dir -ArgumentList @(
    "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = '$title'; $command"
  )
}

Open-Window "HVAC API (port 8000)" (Join-Path $Root "backend") ".\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
Open-Window "Shop portal (port 5173)" (Join-Path $Root "shop-portal") "npm run dev"
Open-Window "Homeowner app (port 8081)" (Join-Path $Root "mobile") "npx expo start --web --port 8081"

Write-Host "Starting... the homeowner app takes about 20 seconds to build the first time."
Start-Sleep -Seconds 8
Start-Process "http://localhost:5173"
Start-Sleep -Seconds 12
Start-Process "http://localhost:8081"
Write-Host "Shop portal:   http://localhost:5173   (demo@coolbreeze.example.com / DemoPassword123!)"
Write-Host "Homeowner app: http://localhost:8081   (tap 'Use demo homeowner')"
Write-Host "Close the three PowerShell windows to stop everything."
