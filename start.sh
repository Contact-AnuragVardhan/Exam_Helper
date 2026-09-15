#!/usr/bin/env bash
set -euo pipefail

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

echo "Starting Exam Helper WhatsApp Bot on port ${PORT:-10000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"
