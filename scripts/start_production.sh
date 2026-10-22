#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DATABASE_URL:?Set DATABASE_URL to the production PostgreSQL database}"
: "${DJANGO_SECRET_KEY:?Set a persistent DJANGO_SECRET_KEY}"
: "${DEALDESK_DATA_DIR:?Set DEALDESK_DATA_DIR to a persistent disk path}"
export DJANGO_DEBUG=false

# Run after the persistent disk is mounted, not during the image build.
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py check --deploy --fail-level ERROR

# One service shares its private disk with one background worker. A separate
# Render worker cannot mount the web service's disk.
python manage.py run_worker &
worker_pid=$!
gunicorn dealdesk.wsgi:application --bind "0.0.0.0:${PORT:-10000}" \
    --workers 1 --threads 2 --timeout 120 --access-logfile - --error-logfile - &
web_pid=$!

shutdown() {
    kill -TERM "$web_pid" "$worker_pid" 2>/dev/null || true
    wait "$web_pid" "$worker_pid" 2>/dev/null || true
}
trap shutdown EXIT
trap 'exit 0' TERM INT

# If either process exits, restart the service instead of leaving uploads queued
# indefinitely while the web process still appears healthy.
set +e
wait -n "$web_pid" "$worker_pid"
exit 1
