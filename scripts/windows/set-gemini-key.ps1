# Saves FREE Google Gemini API keys in backend\.env (only on this computer; never
# uploaded to GitHub) and checks each one works. Several keys spread the load; Google
# counts limits per project, so make each key in a DIFFERENT project (AI Studio >
# Create API key > "Create API key in new project").
#   powershell -ExecutionPolicy Bypass -File scripts\windows\set-gemini-key.ps1
# Get a key (free, sign in with Google): https://aistudio.google.com/apikey
$ErrorActionPreference = "Stop"
$Backend = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "backend"
$EnvFile = Join-Path $Backend ".env"
if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $Backend ".env.example") $EnvFile }

$existing = @()
$current = Get-Content $EnvFile | Where-Object { $_ -match '^\s*HVAC_GEMINI_API_KEY=' } | Select-Object -Last 1
if ($current) { $existing = @(($current -split '=', 2)[1] -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }

$secure = Read-Host "Paste one or more Gemini API keys, separated by commas" -AsSecureString
$typed = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim()
$new = @($typed -split ',' | ForEach-Object { $_.Trim().Trim('"') } | Where-Object { $_ })
foreach ($k in $new) { if ($k.Length -lt 20) { throw "That doesn't look like a Gemini API key." } }
if ($new.Count -eq 0) { throw "No key entered." }
$keys = $new
if ($existing.Count -gt 0) {
  $answer = Read-Host "You already have $($existing.Count) key(s) saved. Add these to them? (Y = add, N = replace)"
  if ($answer -notmatch '^[Nn]') { $keys = @($existing + $new | Select-Object -Unique) }
}
$key = $keys -join ','

# Use Gemini for photo analysis (replaces any Anthropic key line so Gemini is used).
$lines = Get-Content $EnvFile | Where-Object {
  $_ -notmatch '^\s*#?\s*HVAC_GEMINI_API_KEY=' -and
  $_ -notmatch '^\s*HVAC_AI_PROVIDER=' -and
  $_ -notmatch '^\s*HVAC_ANTHROPIC_API_KEY='
}
$lines += "HVAC_AI_PROVIDER=gemini"
$lines += "HVAC_GEMINI_API_KEY=$key"
[IO.File]::WriteAllLines($EnvFile, [string[]]$lines)  # UTF-8 without BOM
Write-Host "Saved $($keys.Count) key(s) to backend\.env" -ForegroundColor Green

Set-Location $Backend
Write-Host "Checking each key with a test image..."
.\.venv\Scripts\python.exe -m app.cli test-ai
if ($LASTEXITCODE -ne 0) {
  throw "It didn't work. The reason is above. If the model isn't available, set HVAC_GEMINI_MODEL in backend\.env to a free model listed in AI Studio."
}
Write-Host "Photo analysis is ON (Gemini). Restart the 'HVAC API' window to use it." -ForegroundColor Green
