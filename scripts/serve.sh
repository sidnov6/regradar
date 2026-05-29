#!/usr/bin/env bash
# Run the RegRadar console + API locally. Open http://localhost:8000
set -e
cd "$(dirname "$0")/.."
exec .venv/bin/uvicorn regradar.server:app --reload --port "${PORT:-8000}"
