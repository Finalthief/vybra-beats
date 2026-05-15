"""SQLAlchemy engine + session factory.

One engine per `Settings.database_url`. Defaults to a SQLite file under the
data directory. Override with `DATABASE_URL` (e.g. Postgres on Railway).
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import Settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def make_engine(settings: Settings) -> Engine:
    """Build an Engine appropriate for SQLite or a real DB URL."""
    url = settings.database_url
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create tables. Idempotent. Called once at app startup."""
    # Import models so they register with Base.metadata.
    from . import db_models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def session_dependency(session_factory: sessionmaker[Session]) -> "callable":
    """Build a FastAPI dependency that yields a Session bound to this app."""

    def _get_session() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    return _get_session
