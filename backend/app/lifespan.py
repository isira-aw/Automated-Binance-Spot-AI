"""Startup and shutdown sequence (§93, §106).

Startup order: validate configuration -> ensure persistent directories ->
connect PostgreSQL -> verify migrations have been applied -> connect Redis ->
verify the model registry against on-disk artifacts -> load persisted state ->
register health probes.

Failures here are surfaced through the health endpoint rather than hidden.
LIVE trading is never enabled by a successful startup (§106).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings
from app.core.errors import ConfigurationError
from app.core.logging_config import get_logger
from app.database.redis_client import check_redis, close_redis, get_redis, init_redis
from app.database.session import (
    alembic_revision,
    check_database,
    dispose_engine,
    init_engine,
    session_scope,
)
from app.ml.registry import demote_broken_production_models, verify_registry_artifacts
from app.models.enums import ComponentHealth
from app.monitoring.health import ComponentStatus, init_health_service
from app.monitoring.log_stream import WebSocketLogHandler
from app.services.app_state import load_application_state, record_shutdown, record_startup
from app.websocket.event_bus import init_event_bus
from app.websocket.manager import init_connection_manager

logger = get_logger("lifespan")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    problems = settings.validate_environment()
    if problems:
        raise ConfigurationError("; ".join(problems))

    settings.paths.ensure()

    bus = init_event_bus(settings.websocket.outbound_queue_size)
    manager = init_connection_manager(
        bus,
        heartbeat_interval=settings.websocket.heartbeat_interval_seconds,
        client_timeout=settings.websocket.client_timeout_seconds,
        max_connections=settings.websocket.max_connections,
    )
    app.state.event_bus = bus
    app.state.connection_manager = manager

    log_handler = WebSocketLogHandler(bus, asyncio.get_running_loop())
    logging.getLogger().addHandler(log_handler)

    init_engine(settings)
    init_redis(settings)

    app.state.startup_problems = []
    await _startup_checks(app, settings)
    _register_health_probes(app, settings)

    logger.info(
        "Backend started",
        extra={
            "event_type": "system_startup",
            "environment": settings.env.value,
            "mode": getattr(app.state, "trading_mode", "UNKNOWN"),
        },
    )

    try:
        yield
    finally:
        logging.getLogger().removeHandler(log_handler)
        try:
            async with session_scope() as session:
                await record_shutdown(session)
        except Exception as exc:
            logger.warning(
                "Could not persist shutdown timestamp",
                extra={"event_type": "system_shutdown_warning"},
                exc_info=exc,
            )
        await close_redis()
        await dispose_engine()
        logger.info("Backend stopped", extra={"event_type": "system_shutdown"})


async def _startup_checks(app: FastAPI, settings: Settings) -> None:
    """Probe dependencies once at startup and record what failed."""
    problems: list[str] = app.state.startup_problems

    try:
        async with session_scope() as session:
            await check_database(session)
            revision = await alembic_revision(session)
            if revision is None:
                problems.append(
                    "Database schema has not been migrated. Run `alembic upgrade head`."
                )
            app.state.schema_revision = revision

            integrity = await verify_registry_artifacts(session, settings)
            app.state.model_registry_report = integrity
            if integrity.production_broken:
                demoted = await demote_broken_production_models(session, integrity)
                problems.append(
                    "Model registry references artifacts that are missing on disk; "
                    f"demoted from PRODUCTION: {', '.join(demoted)}."
                )

            await record_startup(session)
            state = await load_application_state(session, settings)
            app.state.trading_mode = state["mode"].value
            app.state.engine_state = state["engine_state"].value
            app.state.live_armed = state["live_armed"]
    except Exception as exc:
        problems.append(f"Database unavailable at startup: {exc}")
        app.state.schema_revision = None
        app.state.model_registry_report = None
        logger.error(
            "Database startup check failed",
            extra={"event_type": "startup_db_failed"},
            exc_info=exc,
        )

    try:
        await check_redis(get_redis())
    except Exception as exc:
        problems.append(f"Redis unavailable at startup: {exc}")
        logger.error(
            "Redis startup check failed",
            extra={"event_type": "startup_redis_failed"},
            exc_info=exc,
        )


def _register_health_probes(app: FastAPI, settings: Settings) -> None:
    service = init_health_service(settings)

    async def backend() -> ComponentStatus:
        return ComponentStatus("backend", ComponentHealth.ONLINE)

    async def database() -> ComponentStatus:
        async with session_scope() as session:
            await check_database(session)
            revision = await alembic_revision(session)
        if revision is None:
            return ComponentStatus(
                "database",
                ComponentHealth.DEGRADED,
                "Connected, but no migrations have been applied.",
            )
        return ComponentStatus(
            "database", ComponentHealth.ONLINE, metadata={"schema_revision": revision}
        )

    async def redis() -> ComponentStatus:
        await check_redis(get_redis())
        return ComponentStatus("redis", ComponentHealth.ONLINE)

    async def websocket() -> ComponentStatus:
        manager = app.state.connection_manager
        return ComponentStatus(
            "websocket",
            ComponentHealth.ONLINE,
            metadata={"connections": manager.connection_count},
        )

    async def model_registry() -> ComponentStatus:
        async with session_scope() as session:
            report = await verify_registry_artifacts(session, settings)
        if report.production_broken:
            return ComponentStatus(
                "model_registry",
                ComponentHealth.ERROR,
                "A PRODUCTION model artifact is missing or corrupted; "
                "the model cannot be loaded and will not be traded on.",
            )
        if not report.ok:
            return ComponentStatus(
                "model_registry",
                ComponentHealth.DEGRADED,
                "Some non-production model artifacts are missing on disk.",
            )
        return ComponentStatus(
            "model_registry",
            ComponentHealth.ONLINE,
            metadata={"registered_models": report.checked},
        )

    service.register("backend", backend)
    service.register("database", database)
    service.register("redis", redis)
    service.register("websocket", websocket)
    service.register("model_registry", model_registry)

    # Components whose engines are not built yet report NOT_IMPLEMENTED rather
    # than a fabricated healthy status (§96).
    for name in (
        "binance",
        "market_data",
        "trading_engine",
        "risk_engine",
        "technical_engine",
        "scheduler",
    ):
        service.register_static(
            name,
            ComponentHealth.NOT_IMPLEMENTED,
            "Planned in the Tier 1 phase list; not built yet.",
        )

    service.register_static(
        "ollama",
        ComponentHealth.DISABLED
        if not settings.llm.ollama_enabled
        else ComponentHealth.NOT_IMPLEMENTED,
        "Tier 2 component.",
    )
    service.register_static(
        "claude",
        ComponentHealth.DISABLED
        if not settings.llm.claude_enabled
        else ComponentHealth.NOT_IMPLEMENTED,
        "Tier 2 component.",
    )
    service.register_static(
        "news",
        ComponentHealth.DISABLED if not settings.news.enabled else ComponentHealth.NOT_IMPLEMENTED,
        "Tier 2 component.",
    )
