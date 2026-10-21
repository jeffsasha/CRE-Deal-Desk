#!/bin/sh
# Starts DealDesk in demo mode with fictional sample data in var-demo/ (never the real database).
set -e
cd "$(dirname "$0")/.."
export DEALDESK_DEMO=1
.venv/bin/python manage.py migrate
if [ ! -f var-demo/.seeded ]; then
  .venv/bin/python manage.py seed_demo && touch var-demo/.seeded
fi
exec .venv/bin/python manage.py runserver 127.0.0.1:8017
