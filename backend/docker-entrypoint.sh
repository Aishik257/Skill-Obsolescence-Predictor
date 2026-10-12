#!/bin/sh
# Wait for PostgreSQL, apply migrations, then start the API. AUTO_SEED=true loads the sample dataset in the background.
set -e

python - <<'PY'
import sys, time
from sqlalchemy import text
from app.core.config import settings
from app.core.database import make_engine

for attempt in range(1, 61):
    try:
        with make_engine(settings.DATABASE_URL).connect() as conn:
            conn.execute(text("SELECT 1"))
        print("database is ready", flush=True)
        break
    except Exception as exc:  # noqa: BLE001
        print(f"waiting for database ({attempt}/60): {type(exc).__name__}", flush=True)
        time.sleep(2)
else:
    sys.exit("database never became reachable")
PY

alembic upgrade head
exec "$@"
