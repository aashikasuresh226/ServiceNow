# Switches the backend to a hosted Postgres database (free: Neon, https://neon.com).
# The connection string is saved only in backend\.env on this computer (never uploaded).
#   powershell -ExecutionPolicy Bypass -File scripts\windows\set-database.ps1
# In Neon: create a project > Connect > copy the connection string
#   (postgresql://user:password@ep-....neon.tech/neondb?sslmode=require)
# Your current local data (SQLite) is NOT copied; the new database starts empty.
$ErrorActionPreference = "Stop"
$Backend = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "backend"
$EnvFile = Join-Path $Backend ".env"
if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $Backend ".env.example") $EnvFile }

$secure = Read-Host "Paste the Postgres connection string" -AsSecureString
$url = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim().Trim('"').Trim("'")
if ($url -notmatch '^postgres(ql)?(\+asyncpg)?://') { throw "That doesn't look like a Postgres connection string (it starts with postgresql://)." }

$lines = Get-Content $EnvFile | Where-Object { $_ -notmatch '^\s*HVAC_DATABASE_URL=' }
$lines += "HVAC_DATABASE_URL=$url"
[IO.File]::WriteAllLines($EnvFile, [string[]]$lines)  # UTF-8 without BOM
Write-Host "Saved to backend\.env" -ForegroundColor Green

Set-Location $Backend
Write-Host "Creating the tables in the new database..."
.\.venv\Scripts\python.exe -m app.cli secrets
.\.venv\Scripts\python.exe -m app.cli migrate
if ($LASTEXITCODE -ne 0) { throw "Couldn't reach or set up the database. Check the connection string (and that the Neon project isn't paused)." }
.\.venv\Scripts\python.exe -m app.cli check
Write-Host "Done. Close the 'HVAC API' window and run start-demo.ps1 again." -ForegroundColor Green
Write-Host "To go back to the local database, delete the HVAC_DATABASE_URL line in backend\.env."
