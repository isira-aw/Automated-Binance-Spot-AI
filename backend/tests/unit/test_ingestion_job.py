"""IngestionJob/Tracker bookkeeping (§76: pollable status for a background job)."""

from __future__ import annotations

from app.services.historical_ingestion import (
    IngestionJobTracker,
    IngestionResult,
)


def test_new_tracker_has_no_current_job():
    assert IngestionJobTracker().current is None


def test_start_creates_a_running_job():
    tracker = IngestionJobTracker()
    job = tracker.start()
    assert job.running is True
    assert job.finished_at is None
    assert tracker.current is job


def test_finish_marks_the_job_done():
    tracker = IngestionJobTracker()
    job = tracker.start()
    tracker.finish(job)
    assert job.running is False
    assert job.finished_at is not None


def test_total_candles_sums_every_result():
    tracker = IngestionJobTracker()
    job = tracker.start()
    job.results.append(IngestionResult(symbol="BTCUSDT", timeframe="4h", candles_inserted=10))
    job.results.append(IngestionResult(symbol="ETHUSDT", timeframe="4h", candles_inserted=5))
    assert job.total_candles == 15


def test_to_dict_serialises_every_result():
    tracker = IngestionJobTracker()
    job = tracker.start()
    job.results.append(
        IngestionResult(
            symbol="BTCUSDT",
            timeframe="1h",
            pages_fetched=3,
            candles_inserted=100,
            reached_present=True,
            stopped_reason="reached_present",
        )
    )
    payload = job.to_dict()
    assert payload["total_candles_inserted"] == 100
    assert payload["results"][0]["symbol"] == "BTCUSDT"
    assert payload["results"][0]["stopped_reason"] == "reached_present"


def test_a_failed_pair_carries_its_error_without_losing_others():
    tracker = IngestionJobTracker()
    job = tracker.start()
    job.results.append(
        IngestionResult(symbol="ETHUSDT", timeframe="4h", stopped_reason="error", error="boom")
    )
    job.results.append(
        IngestionResult(symbol="BTCUSDT", timeframe="4h", candles_inserted=50, reached_present=True)
    )
    payload = job.to_dict()
    assert payload["results"][0]["error"] == "boom"
    assert payload["results"][1]["error"] is None
    assert payload["total_candles_inserted"] == 50
