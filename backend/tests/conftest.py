"""Test configuration. The database is chosen *before* the app is imported.

By default tests run on a throw-away SQLite file (fast, no services needed). Point
``TEST_DATABASE_URL`` at PostgreSQL to run the identical suite against Postgres.
"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="skillpulse-tests-")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TMP}/test.db")
os.environ["MODEL_DIR"] = f"{_TMP}/models"
os.environ["AUTO_SEED"] = "false"
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_PROVIDER"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402
import app.models  # noqa: E402,F401
from app.main import app  # noqa: E402
from app.utils.cache import analysis_cache  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


def wipe(db) -> None:
    """Delete every row (children first) so tests do not leak into each other."""
    db.rollback()
    if engine.dialect.name == "postgresql":
        names = ", ".join(t.name for t in Base.metadata.sorted_tables)
        db.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    else:
        db.execute(text("UPDATE job_postings SET duplicate_of_id = NULL"))
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
    db.commit()
    analysis_cache.clear()


@pytest.fixture()
def db():
    with SessionLocal() as session:
        wipe(session)
        yield session
        wipe(session)


@pytest.fixture()
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
