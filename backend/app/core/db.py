"""Database engine, session factory and shared column types."""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, MetaData, TypeDecorator, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware datetime that is always stored and returned in UTC.

    Rejects naive datetimes on write so local-time bugs fail loudly, and
    re-attaches UTC on read for databases (SQLite) that drop tzinfo.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use timezone-aware UTC values")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def prepare_database_url(database_url: str) -> tuple[str, dict[str, Any]]:
    """Accept a connection string as hosted Postgres providers show it (Neon, Supabase, ...):
    `postgresql://user:pass@host/db?sslmode=require` -> the async driver's URL + TLS settings.
    TLS certificates are always verified for remote hosts."""
    if database_url.startswith("sqlite"):
        return database_url, {}
    url = make_url(database_url)
    if url.drivername in ("postgres", "postgresql", "postgresql+psycopg2", "postgresql+psycopg"):
        url = url.set(drivername="postgresql+asyncpg")
    query = dict(url.query)
    sslmode = str(query.pop("sslmode", "") or "")
    query.pop("channel_binding", None)  # libpq-only option; asyncpg negotiates it itself
    url = url.set(query=query)
    connect_args: dict[str, Any] = {}
    host = url.host or ""
    local = host in ("", "localhost", "127.0.0.1", "::1")
    if sslmode in ("require", "verify-ca", "verify-full") or (not local and sslmode != "disable"):
        connect_args["ssl"] = ssl.create_default_context()
    if "-pooler" in host:
        # Connection poolers (PgBouncer) don't support prepared-statement caching.
        connect_args["statement_cache_size"] = 0
    return url.render_as_string(hide_password=False), connect_args


def create_engine(database_url: str) -> AsyncEngine:
    url, connect_args = prepare_database_url(database_url)
    if url.startswith("sqlite"):
        return create_async_engine(url)
    return create_async_engine(url, pool_pre_ping=True, pool_recycle=300, connect_args=connect_args)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Yield a session that commits on success and rolls back on error."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
