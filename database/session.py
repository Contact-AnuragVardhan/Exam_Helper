from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app import config
from services.logger import get_logger
from .models import Base

log = get_logger("database")

_engine: Engine | None = None
_engine_url: str | None = None
_session_factory: sessionmaker | None = None
_schema_ready = False


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
    global _engine, _engine_url, _session_factory, _schema_ready

    url = database_url()
    if _engine is not None and _engine_url == url:
        return _engine

    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    backend = "sqlite" if url.startswith("sqlite") else "postgresql"
    log.info("Creating database engine backend=%s", backend)
    _engine = create_engine(url, pool_pre_ping=True, future=True, connect_args=connect_args)
    _engine_url = url
    _schema_ready = False
    _session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=_engine,
        future=True,
    )
    return _engine


def _ensure_artifact_columns(engine: Engine) -> None:
    """Apply tiny idempotent artifact migrations that create_all cannot add to existing tables."""
    inspector = inspect(engine)
    if "exam_helper_exams" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("exam_helper_exams")}
    if "exam_docx" in columns:
        return
    ddl = (
        "ALTER TABLE exam_helper_exams ADD COLUMN IF NOT EXISTS exam_docx BYTEA"
        if engine.dialect.name == "postgresql"
        else "ALTER TABLE exam_helper_exams ADD COLUMN exam_docx BLOB"
    )
    with engine.begin() as conn:
        conn.execute(text(ddl))
    log.info("Added exam_helper_exams.exam_docx artifact column")


def init_db() -> None:
    if not config.DATABASE_AUTO_CREATE_TABLES:
        log.info("Database table auto-creation disabled")
        return
    log.info("Ensuring application database tables exist")
    global _schema_ready
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _ensure_artifact_columns(engine)
    _schema_ready = True
    log.info("Database initialization complete")


def _ensure_schema_if_enabled() -> None:
    global _schema_ready
    if _schema_ready or not config.DATABASE_AUTO_CREATE_TABLES:
        return
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _ensure_artifact_columns(engine)
    _schema_ready = True


def new_session() -> Session:
    global _session_factory
    get_engine()
    _ensure_schema_if_enabled()
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
