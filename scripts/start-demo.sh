#!/usr/bin/env bash
# Starts API, shop portal and homeowner app; Ctrl+C stops all three.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
trap 'kill 0' EXIT

(cd "$ROOT/backend" && .venv/bin/python -m uvicorn app.main:app --port 8000) &
(cd "$ROOT/shop-portal" && npm run dev) &
(cd "$ROOT/mobile" && npx expo start --web --port 8081) &

echo "Shop portal:   http://localhost:5173  (demo@coolbreeze.example.com / DemoPassword123!)"
echo "Homeowner app: http://localhost:8081  (tap 'Use demo homeowner')"
wait
