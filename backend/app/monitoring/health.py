"""Component health aggregation for `/api/v1/system/health` (§43, §105).

Components that belong to phases that are not built yet report
``NOT_IMPLEMENTED`` — never a fabricated ``ONLINE`` (§96).  Components that are
built but switched off in configuration report ``DISABLED``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.core.logging_config import get_logger
from app.core.time_utils import utc_now
from app.models.enums import ComponentHealth

logger = get_logger("monitoring.health")

# Wall-clock budget for a single component probe.  A hung dependency must not
# be able to hang the health endpoint (§53).
PROBE_TIMEOUT_SECONDS = 3.0


@dataclass
class ComponentStatus:
    name: str
    status: ComponentHealth
    detail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status.value}
        if self.detail:
            payload["detail"] = self.detail
        if self.metadata:
            payload.update(self.metadata)
        return payload


@dataclass
class HealthReport:
    components: dict[str, ComponentStatus]
    checked_at: str = field(default_factory=lambda: utc_now().isoformat())

    @property
    def overall(self) -> ComponentHealth:
        """Worst status among components that are expected to be running."""
        relevant = [
            component.status
            for component in self.components.values()
            if component.status
            not in {ComponentHealth.DISABLED, ComponentHealth.NOT_IMPLEMENTED}
        ]
        if any(status is ComponentHealth.ERROR for status in relevant):
            return ComponentHealth.ERROR
        if any(status is ComponentHealth.OFFLINE for status in relevant):
            return ComponentHealth.OFFLINE
        if any(status is ComponentHealth.DEGRADED for status in relevant):
            return ComponentHealth.DEGRADED
        return ComponentHealth.ONLINE

    @property
    def healthy(self) -> bool:
        return self.overall is ComponentHealth.ONLINE

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall.value,
            "checked_at": self.checked_at,
            "components": {
                name: component.to_dict() for name, component in self.components.items()
            },
        }


class HealthService:
    """Runs every component probe concurrently, with per-probe timeouts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._probes: dict[str, Any] = {}

    def register(self, name: str, probe: Any) -> None:
        """Register an async probe returning a :class:`ComponentStatus`."""
        self._probes[name] = probe

    def register_static(
        self, name: str, status: ComponentHealth, detail: str | None = None
    ) -> None:
        async def _static() -> ComponentStatus:
            return ComponentStatus(name=name, status=status, detail=detail)

        self._probes[name] = _static

    async def check(self) -> HealthReport:
        names = list(self._probes)
        results = await asyncio.gather(
            *(self._run_probe(name) for name in names), return_exceptions=False
        )
        return HealthReport(components=dict(zip(names, results, strict=True)))

    async def _run_probe(self, name: str) -> ComponentStatus:
        try:
            return await asyncio.wait_for(self._probes[name](), PROBE_TIMEOUT_SECONDS)
        except TimeoutError:
            return ComponentStatus(
                name=name,
                status=ComponentHealth.DEGRADED,
                detail=f"Health probe timed out after {PROBE_TIMEOUT_SECONDS:.0f}s.",
            )
        except Exception as exc:
            logger.warning(
                "Health probe failed",
                extra={"event_type": "health_probe_failed", "component_name": name},
                exc_info=exc,
            )
            return ComponentStatus(
                name=name, status=ComponentHealth.ERROR, detail=str(exc)
            )


_service: HealthService | None = None


def init_health_service(settings: Settings) -> HealthService:
    global _service
    _service = HealthService(settings)
    return _service


def get_health_service() -> HealthService:
    if _service is None:
        raise RuntimeError("Health service is not initialised.")
    return _service
