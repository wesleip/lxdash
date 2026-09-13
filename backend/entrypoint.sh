#!/bin/sh
set -e

echo "[entrypoint] Running database migrations..."
alembic upgrade head

# Seed the first admin user on first boot.
# Set ADMIN_PASSWORD in .env.production to enable this.
if [ -n "$ADMIN_PASSWORD" ]; then
    python seed.py \
        --username "${ADMIN_USERNAME:-admin}" \
        --email "${ADMIN_EMAIL:-admin@lxdash.local}" \
        --password "$ADMIN_PASSWORD"
fi

echo "[entrypoint] Starting server..."
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${UVICORN_WORKERS:-2}" \
    --no-access-log
