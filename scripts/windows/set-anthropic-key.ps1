# Saves your Anthropic API key in backend\.env (only on this computer; never uploaded
# to GitHub) and checks that it works.
#   powershell -ExecutionPolicy Bypass -File scripts\windows\set-anthropic-key.ps1
# Get a key at https://console.anthropic.com/settings/keys
$ErrorActionPreference = "Stop"
$Backend = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "backend"
$EnvFile = Join-Path $Backend ".env"
if (-not (Test-Path $EnvFile)) { Copy-Item (Join-Path $Backend ".env.example") $EnvFile }

$secure = Read-Host "Paste your Anthropic API key (starts with sk-ant-)" -AsSecureString
$key = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
  [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim()
if (-not $key.StartsWith("sk-ant-")) { throw "That doesn't look like an Anthropic API key (it should start with sk-ant-)." }

# Replace any existing key line (commented or not), then append the new one.
$lines = Get-Content $EnvFile | Where-Object { $_ -notmatch '^\s*#?\s*HVAC_ANTHROPIC_API_KEY=' -and $_ -notmatch '^\s*HVAC_AI_PROVIDER=' }
$lines += "HVAC_ANTHROPIC_API_KEY=$key"
[IO.File]::WriteAllLines($EnvFile, [string[]]$lines)  # UTF-8 without BOM
Write-Host "Saved to backend\.env" -ForegroundColor Green

Set-Location $Backend
Write-Host "Checking the key with a test image..."
.\.venv\Scripts\python.exe -m app.cli test-ai
if ($LASTEXITCODE -ne 0) { throw "The key didn't work. Check it in the Anthropic Console (and that the account has credits)." }
Write-Host "Photo analysis is ON. Restart the 'HVAC API' window to use it." -ForegroundColor Green
