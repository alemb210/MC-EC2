#!/usr/bin/env bash
# Start the MC-EC2 web app at http://127.0.0.1:8000 (override with PORT=...)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtualenv and installing dependencies..."
  python3 -m venv .venv
  .venv/bin/python -m pip install -q -r backend/requirements.txt
fi

if [ ! -d frontend/dist ]; then
  echo "Building frontend..."
  (cd frontend && npm ci && npm run build)
fi

env_args=()
[ -f .env ] && env_args=(--env-file .env)

exec .venv/bin/python -m uvicorn app:app --app-dir backend "${env_args[@]+"${env_args[@]}"}" --reload --port "${PORT:-8000}"
