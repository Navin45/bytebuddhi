#!/bin/sh
set -eu

python /app/scripts/migrate.py

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec gunicorn app.interfaces.api.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers "${WORKERS:-4}" \
  --bind "${HOST:-0.0.0.0}:${PORT:-8000}" \
  --timeout "${GUNICORN_TIMEOUT:-0}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
  --keep-alive 5 \
  --access-logfile - \
  --error-logfile - \
  --capture-output
