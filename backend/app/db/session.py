"""Engine and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import models  # noqa: F401  (registers the tables)

_engine: Engine | None = None


def make_engine(url: str) -> Engine:
    """Create an engine. In-memory SQLite shares one connection so every session sees the data."""
    if url in {"sqlite://", "sqlite:///:memory:"}:
        return create_engine(url, connect_args={"check_same_thread": False},
                             poolclass=StaticPool)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def init_engine(url: str) -> Engine:
    """Create the process-wide engine and its tables."""
    global _engine
    _engine = make_engine(url)
    SQLModel.metadata.create_all(_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database not initialised: call init_engine() first")
    return _engine


def reset_db(engine: Engine | None = None) -> None:
    """Drop and recreate every table (demo reset and tests)."""
    target = engine or get_engine()
    SQLModel.metadata.drop_all(target)
    SQLModel.metadata.create_all(target)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """A session that commits on success and rolls back on error."""
    with Session(engine or get_engine(), expire_on_commit=False) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
