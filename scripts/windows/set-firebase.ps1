# Turns on real verification emails (free Firebase Authentication) for shop sign-up and
# technician invites. Saved only in backend\.env on this computer.
#   powershell -ExecutionPolicy Bypass -File scripts\windows\set-firebase.ps1
# Before running:
#   1. https://console.firebase.google.com > Add project (Google Analytics not needed)
#   2. Build > Authentication > Get started > Sign-in method > Email/Password > Enable > Save
#   3. Project settings (gear) > General > copy "Web API key" (starts with AIza)
#      (if none is shown, add a Web app under "Your apps" and it appears)
$ErrorActionPreference = "Stop"
$Backend = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "backend"
$EnvFile = Join-Path $Backend ".env"
if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $Backend ".env.example") $EnvFile }

$apiKey = (Read-Host "Firebase Web API key (starts with AIza)").Trim().Trim('"')
if ($apiKey -notmatch '^AIza') { throw "Copy the Web API key from Project settings > General." }

$lines = Get-Content $EnvFile | Where-Object {
  $_ -notmatch '^\s*HVAC_FIREBASE_API_KEY=' -and $_ -notmatch '^\s*HVAC_FIREBASE_PROJECT_ID='
}
$lines += "HVAC_FIREBASE_API_KEY=$apiKey"
[IO.File]::WriteAllLines($EnvFile, [string[]]$lines)  # UTF-8 without BOM
Set-Location $Backend
.\.venv\Scripts\python.exe -m app.cli check
Write-Host "Verification emails are ON. Close the 'HVAC API' window and run start-demo.ps1 again." -ForegroundColor Green
