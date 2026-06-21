from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .config import settings

Base = declarative_base()
_POSTGRES_SCHEMA_LOCK_KEY = 94736120814533721


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://") and "+psycopg" not in database_url:
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def _build_engine(database_url: str) -> Engine:
    normalized_url = normalize_database_url(database_url)
    connect_args = {}
    if normalized_url.startswith("sqlite"):
        db_path = normalized_url.replace("sqlite:///", "", 1)
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    return create_engine(
        normalized_url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


engine = _build_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True,
    expire_on_commit=False,
)


def init_database() -> None:
    from . import db_models  # noqa: F401

    with engine.begin() as connection:
        _acquire_schema_lock(connection)
        try:
            Base.metadata.create_all(bind=connection)
        finally:
            _release_schema_lock(connection)


def _acquire_schema_lock(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text("SELECT pg_advisory_lock(:lock_key)"),
        {"lock_key": _POSTGRES_SCHEMA_LOCK_KEY},
    )


def _release_schema_lock(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        text("SELECT pg_advisory_unlock(:lock_key)"),
        {"lock_key": _POSTGRES_SCHEMA_LOCK_KEY},
    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
