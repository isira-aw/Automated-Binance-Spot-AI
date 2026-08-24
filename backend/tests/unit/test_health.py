"""Health aggregation semantics (§43, §96, §105)."""

from __future__ import annotations

import asyncio

from app.models.enums import ComponentHealth
from app.monitoring.health import ComponentStatus, HealthService
from tests.conftest import make_settings


def service() -> HealthService:
    return HealthService(make_settings(env="testing"))


async def test_all_online_reports_online():
    svc = service()
    svc.register_static("backend", ComponentHealth.ONLINE)
    svc.register_static("database", ComponentHealth.ONLINE)
    report = await svc.check()
    assert report.overall is ComponentHealth.ONLINE
    assert report.healthy is True


async def test_error_dominates_degraded():
    svc = service()
    svc.register_static("database", ComponentHealth.ERROR)
    svc.register_static("redis", ComponentHealth.DEGRADED)
    assert (await svc.check()).overall is ComponentHealth.ERROR


async def test_unbuilt_and_disabled_components_do_not_make_the_system_unhealthy():
    """A Tier 2 component that is off must not degrade Tier 1 health (§6)."""
    svc = service()
    svc.register_static("backend", ComponentHealth.ONLINE)
    svc.register_static("claude", ComponentHealth.DISABLED)
    svc.register_static("binance", ComponentHealth.NOT_IMPLEMENTED)
    report = await svc.check()
    assert report.overall is ComponentHealth.ONLINE
    assert report.components["claude"].status is ComponentHealth.DISABLED


async def test_a_raising_probe_becomes_an_error_not_a_crash():
    svc = service()

    async def broken() -> ComponentStatus:
        raise RuntimeError("connection refused")

    svc.register("database", broken)
    report = await svc.check()
    assert report.components["database"].status is ComponentHealth.ERROR
    assert "connection refused" in (report.components["database"].detail or "")


async def test_a_hanging_probe_times_out_rather_than_hanging_the_endpoint():
    svc = service()

    async def hanging() -> ComponentStatus:
        await asyncio.sleep(30)
        raise AssertionError("unreachable")

    svc.register("binance", hanging)
    import app.monitoring.health as health_module

    original = health_module.PROBE_TIMEOUT_SECONDS
    health_module.PROBE_TIMEOUT_SECONDS = 0.05
    try:
        report = await svc.check()
    finally:
        health_module.PROBE_TIMEOUT_SECONDS = original
    assert report.components["binance"].status is ComponentHealth.DEGRADED


async def test_report_serialises_for_the_api():
    svc = service()
    svc.register_static("backend", ComponentHealth.ONLINE)
    payload = (await svc.check()).to_dict()
    assert payload["overall"] == "ONLINE"
    assert payload["components"]["backend"]["status"] == "ONLINE"
    assert "checked_at" in payload
