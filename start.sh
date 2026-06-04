#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Working directory: $(pwd)"
echo "Running database migrations..."
alembic -c "$SCRIPT_DIR/alembic.ini" stamp a1b2c3d4e5f6 2>/dev/null || true
alembic -c "$SCRIPT_DIR/alembic.ini" upgrade head

echo "Starting server..."
cd "$SCRIPT_DIR/backend"
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
