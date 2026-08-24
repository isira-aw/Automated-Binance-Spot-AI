"""Pure dataclass behaviour of the integrity report (§17)."""

from __future__ import annotations

from app.services.data_integrity import IntegrityReport


def test_report_with_no_issues_is_clean():
    report = IntegrityReport(symbol="BTCUSDT", timeframe="4h", candle_count=10)
    assert report.is_clean is True


def test_missing_candles_alone_does_not_mark_dirty():
    """A gap is a coverage problem, not a corruption -- it's surfaced via
    missing_candles, not treated the same as bad data."""
    report = IntegrityReport(symbol="BTCUSDT", timeframe="4h", missing_candles=5)
    assert report.is_clean is True


def test_any_violation_marks_the_report_dirty():
    for field_name in (
        "duplicate_open_times",
        "misaligned_timestamps",
        "ohlc_violations",
        "non_positive_values",
    ):
        report = IntegrityReport(symbol="BTCUSDT", timeframe="4h")
        if field_name == "duplicate_open_times":
            report.duplicate_open_times = 1
        else:
            getattr(report, field_name).append("2024-01-01T00:00:00+00:00")
        assert report.is_clean is False, field_name


def test_abnormal_moves_alone_do_not_mark_dirty():
    """A large real move is flagged for review, not treated as corrupt data."""
    report = IntegrityReport(symbol="BTCUSDT", timeframe="4h")
    report.abnormal_moves.append("2024-01-01T00:00:00+00:00")
    assert report.is_clean is True


def test_to_dict_caps_each_list_at_twenty_entries():
    report = IntegrityReport(symbol="BTCUSDT", timeframe="4h")
    report.ohlc_violations = [f"t{i}" for i in range(50)]
    assert len(report.to_dict()["ohlc_violations"]) == 20
