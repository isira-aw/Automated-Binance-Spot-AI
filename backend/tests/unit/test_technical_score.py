"""Technical component score: the §30a mapping from indicators to [0,1]."""

from __future__ import annotations

import pytest

from app.signals.technical_score import compute_technical_score

NEUTRAL = {
    "sma_20": None, "sma_50": None, "rsi_14": None, "macd": None, "macd_histogram": None,
    "plus_di": None, "minus_di": None, "adx": None, "structure_trend": None,
    "is_higher_high": False, "is_higher_low": False, "is_lower_high": False, "is_lower_low": False,
    "break_of_structure": False, "false_breakout": False, "breakout": False, "breakdown": False,
    "volatility_percentile_100": None,
}


def features(**overrides) -> dict:
    return {**NEUTRAL, **overrides}


class TestNoData:
    def test_all_missing_indicators_yield_neutral_score_and_zero_confidence(self):
        score, confidence, details = compute_technical_score(features())
        assert score == pytest.approx(0.5)
        assert confidence == pytest.approx(0.0)
        assert details["available_count"] == 0


class TestDirectionality:
    def test_a_clearly_bullish_setup_scores_above_half(self):
        score, confidence, _ = compute_technical_score(
            features(
                sma_20=105, sma_50=100, rsi_14=70, macd=1.0, macd_histogram=0.5,
                plus_di=30, minus_di=10, adx=35, structure_trend="BULLISH",
                is_higher_high=True,
            )
        )
        assert score > 0.5
        assert confidence > 0

    def test_a_clearly_bearish_setup_scores_below_half(self):
        score, confidence, _ = compute_technical_score(
            features(
                sma_20=95, sma_50=100, rsi_14=30, macd=-1.0, macd_histogram=-0.5,
                plus_di=10, minus_di=30, adx=35, structure_trend="BEARISH",
                is_lower_low=True,
            )
        )
        assert score < 0.5
        assert confidence > 0

    def test_bullish_and_bearish_are_symmetric_around_neutral(self):
        bullish, _, _ = compute_technical_score(
            features(sma_20=102, sma_50=100, rsi_14=60)
        )
        bearish, _, _ = compute_technical_score(
            features(sma_20=98, sma_50=100, rsi_14=40)
        )
        assert bullish - 0.5 == pytest.approx(0.5 - bearish, abs=1e-9)

    def test_conflicting_indicators_pull_the_score_toward_neutral(self):
        """Bullish trend, bearish momentum -- the two should partly cancel."""
        score, confidence, _ = compute_technical_score(
            features(sma_20=105, sma_50=100, rsi_14=20)
        )
        assert 0.3 < score < 0.7


class TestConfidence:
    def test_more_available_subsignals_raise_confidence_at_equal_conviction(self):
        one_signal = compute_technical_score(features(sma_20=110, sma_50=100))
        two_signals = compute_technical_score(
            features(sma_20=110, sma_50=100, rsi_14=90)
        )
        assert two_signals[1] >= one_signal[1]

    def test_extreme_volatility_caps_confidence(self):
        calm = compute_technical_score(
            features(sma_20=110, sma_50=100, volatility_percentile_100=0.5)
        )
        chaotic = compute_technical_score(
            features(sma_20=110, sma_50=100, volatility_percentile_100=1.0)
        )
        assert chaotic[1] < calm[1]

    def test_confidence_is_always_in_unit_interval(self):
        for kwargs in (
            {"sma_20": 1000, "sma_50": 100},  # extreme trend
            {"rsi_14": 100},
            {},
        ):
            _, confidence, _ = compute_technical_score(features(**kwargs))
            assert 0.0 <= confidence <= 1.0


class TestStructureIntegration:
    def test_a_false_breakout_argues_against_its_own_direction(self):
        with_false_breakout = compute_technical_score(
            features(breakout=True, false_breakout=True)
        )
        without = compute_technical_score(features(breakout=True, false_breakout=False))
        # False breakout should not be *more* bullish than a clean breakout.
        assert with_false_breakout[0] <= without[0] + 1e-9

    def test_higher_high_alone_leans_bullish(self):
        score, _, _ = compute_technical_score(features(is_higher_high=True))
        assert score > 0.5

    def test_lower_low_alone_leans_bearish(self):
        score, _, _ = compute_technical_score(features(is_lower_low=True))
        assert score < 0.5


class TestDetailsForAudit:
    def test_details_record_every_subsignal_for_the_audit_trail(self):
        _, _, details = compute_technical_score(features(sma_20=105, sma_50=100))
        assert set(details["subsignals"]) == {
            "trend",
            "momentum",
            "directional_movement",
            "structure",
        }
        assert details["version"] == "v1"

    def test_score_is_always_in_unit_interval_across_extreme_inputs(self):
        for kwargs in (
            {"sma_20": 1e9, "sma_50": 1},
            {"rsi_14": 0},
            {"rsi_14": 100},
            {"plus_di": 1000, "minus_di": 0, "adx": 1000},
        ):
            score, _, _ = compute_technical_score(features(**kwargs))
            assert 0.0 <= score <= 1.0
