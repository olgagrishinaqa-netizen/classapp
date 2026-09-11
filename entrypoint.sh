#!/usr/bin/env bash
set -euo pipefail

# Fail fast if required env vars are missing
: "${SECRET_KEY:?SECRET_KEY is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required}"
: "${DATABASE_URL:?DATABASE_URL is required}"

# Wait for the database to be ready using psycopg2
echo "Waiting for database to become available..."
python - <<'PY'
import os, time, sys
import psycopg2

url = os.environ.get('DATABASE_URL')
if not url:
    print('DATABASE_URL not set', file=sys.stderr)
    sys.exit(2)

# psycopg2 does not understand SQLAlchemy's driver-qualified URL scheme.
if url.startswith('postgresql+psycopg2://'):
    url = 'postgresql://' + url.removeprefix('postgresql+psycopg2://')

attempts = 0
max_attempts = int(os.environ.get('DB_WAIT_ATTEMPTS', '30'))
wait = float(os.environ.get('DB_WAIT_INTERVAL', '2'))
while True:
    try:
        conn = psycopg2.connect(dsn=url, connect_timeout=3)
        conn.close()
        print('Database is available')
        sys.exit(0)
    except Exception as e:
        attempts += 1
        if attempts >= max_attempts:
            print(f'Database not available after {attempts} attempts: {e}', file=sys.stderr)
            sys.exit(3)
        print(f'Database not ready yet: {e}; retrying in {wait}s...')
        time.sleep(wait)
PY

# Execute the container command (e.g. gunicorn)
exec "$@"
