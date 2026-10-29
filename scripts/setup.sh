#!/usr/bin/env bash
# One-time setup on macOS / Linux.  Usage: ./scripts/setup.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
node -e 'const m=+process.versions.node.split(".")[0]; if (m < 22) { console.error("Node 22+ required"); process.exit(1) }'

cd "$ROOT/backend"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e ".[dev]" -q
[ -f .env ] || cp .env.example .env
.venv/bin/python -m app.cli reset-demo

cd "$ROOT/mobile" && npm install --no-audit --no-fund && { [ -f .env ] || cp .env.example .env; }
cd "$ROOT/shop-portal" && npm install --no-audit --no-fund && { [ -f .env ] || cp .env.example .env; }
echo "Setup complete. Start with: ./scripts/start-demo.sh"
