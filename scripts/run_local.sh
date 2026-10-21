#!/bin/sh
# Runs your real local DealDesk (not demo): web app on 127.0.0.1:8020 plus the
# background worker (document processing and reminders). Data lives in var/.
cd "$(dirname "$0")/.."
if lsof -nP -iTCP:8020 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "DealDesk is already running at http://localhost:8020 — nothing to start."
  exit 0
fi
.venv/bin/python manage.py migrate --noinput || exit 1
.venv/bin/python manage.py run_worker &
WORKER=$!
trap 'kill $WORKER 2>/dev/null' EXIT INT TERM
.venv/bin/python manage.py runserver 127.0.0.1:8020 --noreload
