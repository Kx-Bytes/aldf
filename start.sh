#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Working directory: $(pwd)"
echo "Fixing alembic version state..."

# Clear conflicting alembic version rows using Python
python3 -c "
import os
import sqlalchemy
engine = sqlalchemy.create_engine(os.environ['DATABASE_URL'].replace('postgresql://', 'postgresql+psycopg2://', 1))
with engine.connect() as conn:
    conn.execute(sqlalchemy.text('DELETE FROM alembic_version'))
    conn.commit()
print('alembic_version cleared')
"

echo "Stamping final migration..."
alembic -c "$SCRIPT_DIR/alembic.ini" stamp a1b2c3d4e5f6

echo "Running database migrations..."
alembic -c "$SCRIPT_DIR/alembic.ini" upgrade head

echo "Starting server..."
cd "$SCRIPT_DIR/backend"
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
