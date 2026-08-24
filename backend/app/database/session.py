"""Async engine / session management and DB health checks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql import text

from app.config import Settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> AsyncEngine:
    """Create the process-wide async engine (idempotent)."""
    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(
            settings.database.async_url,
            echo=settings.database.echo,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_pre_ping=True,
        )
        _session_factory = async_sessionmaker(
            _engine, expire_on_commit=False, class_=AsyncSession
        )
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine is not initialised; call init_engine().")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database engine is not initialised; call init_engine().")
    return _session_factory


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional scope for background workers and services."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def check_database(session: AsyncSession) -> bool:
    result = await session.execute(text("SELECT 1"))
    return result.scalar_one() == 1


async def alembic_revision(session: AsyncSession) -> str | None:
    """Current migration revision, or ``None`` if migrations never ran (§3)."""
    result = await session.execute(
        text(
            "SELECT version_num FROM alembic_version LIMIT 1"
        ).execution_options(postgresql_readonly=False)
    )
    row = result.first()
    return row[0] if row else None
