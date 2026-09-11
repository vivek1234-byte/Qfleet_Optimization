"""
Engine, session factory, and the FastAPI dependency.

The engine is created lazily and cached, so importing this module does not
open a file or a socket. That matters for the test suite, which points
``QGF_DATABASE_URL`` at a temporary database *after* the application modules
have been imported.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from config import settings

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_Session: Optional[sessionmaker[Session]] = None
_engine_url: Optional[str] = None


def _make_engine(url: str) -> Engine:
    kwargs: dict = {"echo": settings.DB_ECHO, "future": True, "pool_pre_ping": True}

    if url.startswith("sqlite"):
        # SQLite refuses cross-thread use by default, and uvicorn runs request
        # handlers on a thread pool. The session is still per-request, so the
        # connection is never shared between two live requests.
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs.pop("pool_pre_ping", None)

        # Create the directory for a file-backed database before connecting;
        # SQLite will not make one and the error it gives is unhelpful.
        prefix = "sqlite:///"
        if url.startswith(prefix) and not url.startswith(prefix + ":memory:"):
            path = Path(url[len(prefix) :])
            if str(path) not in {"", ":memory:"}:
                path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(url, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver glue
            cursor = dbapi_connection.cursor()
            # WAL survives a hard kill mid-write, which a demo laptop does get.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_engine() -> Engine:
    """The process-wide engine, created on first use."""
    global _engine, _Session, _engine_url
    url = settings.DATABASE_URL
    if _engine is None or _engine_url != url:
        if _engine is not None:
            _engine.dispose()
        _engine = _make_engine(url)
        _Session = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
        _engine_url = url
        # Never log the URL itself: it may carry a password.
        logger.info("Accounts database ready (%s)", url.split("://", 1)[0])
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _Session is not None
    return _Session


def reset_engine() -> None:
    """Drop the cached engine. Used by tests when they repoint the database."""
    global _engine, _Session, _engine_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None
    _engine_url = None


@contextmanager
def session_scope() -> Iterator[Session]:
    """A transactional session for scripts and startup tasks."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """
    FastAPI dependency: one session per request, always closed.

    No commit here. Routes commit explicitly, so a handler that raises halfway
    through cannot leave a half-written change behind.
    """
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
