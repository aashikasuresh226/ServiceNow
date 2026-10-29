# One-time setup on Windows. Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File scripts\windows\setup.ps1
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
# Native commands (pip, npm) don't stop the script on failure by themselves.
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE). See the messages above." } }

# --- Check prerequisites -----------------------------------------------------------
Step "Checking Python and Node"
$PyExe = $null
$PyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $PyExe = "py"; $PyArgs = @("-3") }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $PyExe = "python" }
if (-not $PyExe) { throw "Python 3.12+ not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH')." }
$pyVersion = & $PyExe @PyArgs -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$pyVersion -lt [version]"3.12") { throw "Python $pyVersion found; 3.12 or newer is required." }
Write-Host "Python $pyVersion"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js not found. Install Node 22 LTS from https://nodejs.org/" }
$nodeMajor = [int]((node --version).TrimStart("v").Split(".")[0])
if ($nodeMajor -lt 22) { throw "Node $(node --version) found; Node 22 LTS or newer is required." }
Write-Host "Node $(node --version)"

# --- Backend ---------------------------------------------------------------------------
Step "Setting up the backend (Python virtual environment + packages)"
Set-Location (Join-Path $Root "backend")
if (-not (Test-Path ".venv")) { & $PyExe @PyArgs -m venv .venv; Check "Creating the virtual environment" }
$VenvPy = Join-Path (Get-Location) ".venv\Scripts\python.exe"
& $VenvPy -m pip install --upgrade pip --quiet; Check "Upgrading pip"
& $VenvPy -m pip install -e ".[dev]" --quiet; Check "Installing backend packages"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }

Step "Creating the demo database"
& $VenvPy -m app.cli reset-demo; Check "Creating the demo database"

# --- Homeowner app -----------------------------------------------------------------------
Step "Installing the homeowner app (this can take a few minutes)"
Set-Location (Join-Path $Root "mobile")
npm install --no-audit --no-fund; Check "Installing the homeowner app"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }

# --- Shop portal -------------------------------------------------------------------------
Step "Installing the shop portal"
Set-Location (Join-Path $Root "shop-portal")
npm install --no-audit --no-fund; Check "Installing the shop portal"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }

Set-Location $Root
Write-Host "`nSetup complete. Start the demo with:" -ForegroundColor Green
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\windows\start-demo.ps1"
