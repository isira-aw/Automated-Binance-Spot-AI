"""The Phase 16 scheduler loop itself: lifecycle, tick accounting, and
health reporting -- independent of what a tick actually does (that is
``monitor_open_positions``, covered by its own DB integration tests).
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

import app.scheduler.service as scheduler_module
from app.models.enums import ComponentHealth
from app.scheduler.service import SchedulerService
from tests.conftest import make_settings


@asynccontextmanager
async def _fake_session_scope():
    yield object()


@pytest.fixture(autouse=True)
def _patch_session_scope(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(scheduler_module, "session_scope", _fake_session_scope)


def _scheduler(monkeypatch: pytest.MonkeyPatch, tick_fn=None, **scheduler_overrides):
    settings = make_settings(scheduler={"interval_seconds": 1, **scheduler_overrides})

    async def default_tick(session, settings_arg, binance):
        return 0

    monkeypatch.setattr(scheduler_module, "monitor_open_positions", tick_fn or default_tick)
    return SchedulerService(settings, lambda: None)


class TestLifecycle:
    async def test_starting_runs_a_tick_immediately(self, monkeypatch: pytest.MonkeyPatch):
        service = _scheduler(monkeypatch)
        await service.start()
        try:
            await asyncio.sleep(0.05)
            assert service.tick_count >= 1
            assert service.running is True
        finally:
            await service.stop()

    async def test_stopping_halts_further_ticks(self, monkeypatch: pytest.MonkeyPatch):
        service = _scheduler(monkeypatch)
        await service.start()
        await asyncio.sleep(0.05)
        await service.stop()
        count_after_stop = service.tick_count

        await asyncio.sleep(0.05)
        assert service.tick_count == count_after_stop
        assert service.running is False

    async def test_disabled_by_configuration_never_starts(self, monkeypatch: pytest.MonkeyPatch):
        service = _scheduler(monkeypatch, enabled=False)
        await service.start()
        await asyncio.sleep(0.05)
        assert service.running is False
        assert service.tick_count == 0


class TestErrorHandling:
    async def test_a_failing_tick_is_recorded_but_does_not_stop_the_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        async def failing_tick(session, settings_arg, binance):
            raise RuntimeError("no connectivity")

        service = _scheduler(monkeypatch, tick_fn=failing_tick)
        await service.start()
        try:
            await asyncio.sleep(0.05)
            assert service.tick_count >= 1
            assert service.last_error is not None
            assert "no connectivity" in service.last_error
        finally:
            await service.stop()

    async def test_a_later_successful_tick_clears_the_previous_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        calls = {"n": 0}

        async def flaky_tick(session, settings_arg, binance):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("first tick fails")
            return 0

        service = _scheduler(monkeypatch, tick_fn=flaky_tick, interval_seconds=1)
        # Drive ticks directly rather than waiting on real sleeps between them.
        await service._tick()
        assert service.last_error is not None
        await service._tick()
        assert service.last_error is None
        assert service.tick_count == 2


class TestHealthProbe:
    async def test_disabled_reports_disabled(self, monkeypatch: pytest.MonkeyPatch):
        service = _scheduler(monkeypatch, enabled=False)
        status = await service.probe()
        assert status.status is ComponentHealth.DISABLED

    async def test_not_started_reports_offline(self, monkeypatch: pytest.MonkeyPatch):
        service = _scheduler(monkeypatch)
        status = await service.probe()
        assert status.status is ComponentHealth.OFFLINE

    async def test_running_cleanly_reports_online_with_tick_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        service = _scheduler(monkeypatch)
        await service.start()
        try:
            await asyncio.sleep(0.05)
            status = await service.probe()
            assert status.status is ComponentHealth.ONLINE
            assert status.metadata["tick_count"] >= 1
        finally:
            await service.stop()

    async def test_a_failed_tick_reports_degraded(self, monkeypatch: pytest.MonkeyPatch):
        async def failing_tick(session, settings_arg, binance):
            raise RuntimeError("boom")

        service = _scheduler(monkeypatch, tick_fn=failing_tick)
        await service.start()
        try:
            await asyncio.sleep(0.05)
            status = await service.probe()
            assert status.status is ComponentHealth.DEGRADED
            assert "boom" in (status.detail or "")
        finally:
            await service.stop()
