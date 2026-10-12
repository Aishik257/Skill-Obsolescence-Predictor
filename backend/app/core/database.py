"""SQLAlchemy engine, session factory and declarative base."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def make_engine(url: str) -> Engine:
    """Create an engine; SQLite is supported for tests only."""
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        # Pin the psycopg2 driver explicitly; newer SQLAlchemy releases may default to psycopg3.
        url = "postgresql+psycopg2://" + url.split("://", 1)[1]
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)


engine = make_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_factory() -> sessionmaker:
    """FastAPI dependency returning the session factory (used by background pipeline runs; overridable in tests)."""
    return SessionLocal
