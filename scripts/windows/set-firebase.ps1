# Turns on real emails (free Firebase Authentication) for shop sign-up and technician invites.
# Saved only in backend\.env on this computer.
#   powershell -ExecutionPolicy Bypass -File scripts\windows\set-firebase.ps1
# Before running:
#   1. https://console.firebase.google.com > Add project (Google Analytics not needed)
#   2. Build > Authentication > Get started > Sign-in method > Email/Password >
#      turn on "Email link (passwordless sign-in)" > Save
#   3. Project settings (gear) > General > Your apps > Web (</>) > register an app,
#      then copy apiKey and projectId from the config shown
# "localhost" is already an authorized domain; add your real domain later
# (Authentication > Settings > Authorized domains).
$ErrorActionPreference = "Stop"
$Backend = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "backend"
$EnvFile = Join-Path $Backend ".env"
if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $Backend ".env.example") $EnvFile }

$apiKey = (Read-Host "Firebase apiKey (starts with AIza)").Trim().Trim('"')
$project = (Read-Host "Firebase projectId").Trim().Trim('"')
if ($apiKey -notmatch '^AIza' -or -not $project) { throw "Copy apiKey and projectId from Project settings > General > Your apps." }

$lines = Get-Content $EnvFile | Where-Object {
  $_ -notmatch '^\s*HVAC_FIREBASE_API_KEY=' -and $_ -notmatch '^\s*HVAC_FIREBASE_PROJECT_ID='
}
$lines += "HVAC_FIREBASE_API_KEY=$apiKey"
$lines += "HVAC_FIREBASE_PROJECT_ID=$project"
[IO.File]::WriteAllLines($EnvFile, [string[]]$lines)  # UTF-8 without BOM
Set-Location $Backend
.\.venv\Scripts\python.exe -m app.cli check
Write-Host "Email links are ON. Close the 'HVAC API' window and run start-demo.ps1 again." -ForegroundColor Green
