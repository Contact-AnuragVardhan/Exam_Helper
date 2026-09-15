from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app import config
from services.logger import get_logger
from .models import Base

log = get_logger("database")

_engine: Engine | None = None
_engine_url: str | None = None
_session_factory: sessionmaker | None = None


def _normalize_database_url(value: str) -> str:
    url = (value or "").strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def database_url() -> str:
    url = _normalize_database_url(config.DATABASE_URL)
    if not url:
        raise RuntimeError("DATABASE_URL is required.")
    return url


def get_engine() -> Engine:
    global _engine, _engine_url, _session_factory

    url = database_url()
    if _engine is not None and _engine_url == url:
        return _engine

    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    backend = "sqlite" if url.startswith("sqlite") else "postgresql"
    log.info("Creating database engine backend=%s", backend)
    _engine = create_engine(url, pool_pre_ping=True, future=True, connect_args=connect_args)
    _engine_url = url
    _session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=_engine,
        future=True,
    )
    return _engine


def init_db() -> None:
    if not config.DATABASE_AUTO_CREATE_TABLES:
        log.info("Database table auto-creation disabled")
        return
    log.info("Ensuring application database tables exist")
    Base.metadata.create_all(bind=get_engine())
    log.info("Database initialization complete")


def new_session() -> Session:
    global _session_factory
    get_engine()
    assert _session_factory is not None
    return _session_factory()


@contextmanager
def db_session() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        log.exception("Database transaction rolled back")
        raise
    finally:
        session.close()
