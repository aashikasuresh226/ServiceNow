# Saves a FREE Google Gemini API key in backend\.env (only on this computer; never
# uploaded to GitHub) and checks that photo analysis works.
#   powershell -ExecutionPolicy Bypass -File scripts\windows\set-gemini-key.ps1
# Get a key (free, sign in with Google): https://aistudio.google.com/apikey
$ErrorActionPreference = "Stop"
$Backend = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "backend"
$EnvFile = Join-Path $Backend ".env"
if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $Backend ".env.example") $EnvFile }

$secure = Read-Host "Paste your Gemini API key (from aistudio.google.com/apikey)" -AsSecureString
$key = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim()
if ($key.Length -lt 20) { throw "That doesn't look like a Gemini API key." }

# Use Gemini for photo analysis (replaces any Anthropic key line so Gemini is used).
$lines = Get-Content $EnvFile | Where-Object {
  $_ -notmatch '^\s*#?\s*HVAC_GEMINI_API_KEY=' -and
  $_ -notmatch '^\s*HVAC_AI_PROVIDER=' -and
  $_ -notmatch '^\s*HVAC_ANTHROPIC_API_KEY='
}
$lines += "HVAC_AI_PROVIDER=gemini"
$lines += "HVAC_GEMINI_API_KEY=$key"
[IO.File]::WriteAllLines($EnvFile, [string[]]$lines)  # UTF-8 without BOM
Write-Host "Saved to backend\.env" -ForegroundColor Green

Set-Location $Backend
Write-Host "Checking the key with a test image..."
.\.venv\Scripts\python.exe -m app.cli test-ai
if ($LASTEXITCODE -ne 0) {
  throw "It didn't work. The reason is above. If the model isn't available, set HVAC_GEMINI_MODEL in backend\.env to a free model listed in AI Studio."
}
Write-Host "Photo analysis is ON (Gemini). Restart the 'HVAC API' window to use it." -ForegroundColor Green
