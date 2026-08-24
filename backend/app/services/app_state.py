"""Persisted application state (§89, §90).

The backend never assumes a zero starting state on restart: mode, engine state,
and the emergency-stop flag are read back from ``system_settings``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, TradingMode
from app.core.time_utils import utc_now
from app.models.enums import EngineState
from app.models.system import SystemSetting

KEY_TRADING_MODE = "trading.mode"
KEY_ENGINE_STATE = "trading.engine_state"
KEY_LIVE_ARMED = "trading.live_armed"
KEY_LAST_SHUTDOWN = "system.last_shutdown_at"
KEY_LAST_STARTUP = "system.last_startup_at"


async def get_setting(session: AsyncSession, key: str) -> Any | None:
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key == key)
    )
    row = result.scalar_one_or_none()
    return None if row is None else row.value.get("value")


async def set_setting(
    session: AsyncSession, key: str, value: Any, *, description: str | None = None
) -> None:
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key == key)
    )
    row = result.scalar_one_or_none()
    if row is None:
        session.add(
            SystemSetting(key=key, value={"value": value}, description=description)
        )
    else:
        row.value = {"value": value}
        if description is not None:
            row.description = description


async def load_application_state(
    session: AsyncSession, settings: Settings
) -> dict[str, Any]:
    """Read persisted state, falling back to safe configured defaults.

    LIVE is never restored implicitly: even if the persisted mode was LIVE, the
    arm flag must also be set *and* ``LIVE_TRADING_ENABLED`` must be true (§12,
    §106).  Otherwise the system comes back in PAPER.
    """
    stored_mode = await get_setting(session, KEY_TRADING_MODE)
    stored_engine = await get_setting(session, KEY_ENGINE_STATE)
    live_armed = bool(await get_setting(session, KEY_LIVE_ARMED) or False)

    try:
        mode = TradingMode(stored_mode) if stored_mode else settings.trading.mode
    except ValueError:
        mode = settings.trading.mode

    if mode is TradingMode.LIVE and not (
        live_armed and settings.trading.live_trading_enabled
    ):
        mode = TradingMode.PAPER
        live_armed = False

    try:
        engine_state = (
            EngineState(stored_engine) if stored_engine else EngineState.PAUSED
        )
    except ValueError:
        engine_state = EngineState.PAUSED

    return {
        "mode": mode,
        "engine_state": engine_state,
        "live_armed": live_armed,
        "live_trading_enabled": settings.trading.live_trading_enabled,
        "last_shutdown_at": await get_setting(session, KEY_LAST_SHUTDOWN),
    }


async def record_startup(session: AsyncSession) -> None:
    await set_setting(
        session,
        KEY_LAST_STARTUP,
        utc_now().isoformat(),
        description="Timestamp of the most recent backend startup.",
    )


async def record_shutdown(session: AsyncSession) -> None:
    await set_setting(
        session,
        KEY_LAST_SHUTDOWN,
        utc_now().isoformat(),
        description="Timestamp of the most recent clean backend shutdown.",
    )
