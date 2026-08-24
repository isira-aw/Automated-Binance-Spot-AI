"""Clock handling (§72): the laptop clock is never trusted."""

from __future__ import annotations

from app.binance.time_sync import TimeSync


def test_offset_is_measured_against_the_request_midpoint():
    """Latency should contribute at most half the round trip to the estimate.

    Local clock is 1000ms behind; the round trip takes 200ms, so the true
    offset is +1000 and a naive endpoint comparison would report +1100.
    """
    sync = TimeSync()
    sync.observe(sent_ms=1_000_000, server_ms=1_001_100, received_ms=1_000_200)
    assert sync.offset_ms == 1000
    assert sync.round_trip_ms == 200


def test_timestamp_applies_the_offset():
    sync = TimeSync()
    sync.observe(sent_ms=1_000_000, server_ms=1_005_000, received_ms=1_000_000)
    assert sync.timestamp_ms(now_ms=2_000_000) == 2_005_000


def test_negative_offset_for_a_fast_local_clock():
    sync = TimeSync()
    sync.observe(sent_ms=1_000_000, server_ms=999_000, received_ms=1_000_000)
    assert sync.offset_ms == -1000
    assert sync.timestamp_ms(now_ms=1_000_000) == 999_000


def test_unsynchronised_until_first_observation():
    sync = TimeSync()
    assert sync.synchronised is False
    sync.observe(sent_ms=1, server_ms=1, received_ms=1)
    assert sync.synchronised is True


def test_invalidate_forces_resync_rather_than_widening_recv_window():
    """A -1021 rejection must mark the estimate untrusted, not adjust the window."""
    sync = TimeSync()
    sync.observe(sent_ms=1_000_000, server_ms=1_000_000, received_ms=1_000_000)
    recorded_offset = sync.offset_ms
    sync.invalidate()
    assert sync.synchronised is False
    # The offset is retained for diagnostics; only its trustworthiness changes.
    assert sync.offset_ms == recorded_offset
