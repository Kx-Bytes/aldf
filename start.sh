#!/bin/bash
set -e

# Move to repo root where alembic.ini lives
cd "$(dirname "$0")"

echo "Running database migrations..."
alembic upgrade head

echo "Starting server..."
cd backend
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
