"""Signal fusion: weighted combination and §86 thresholds."""

from __future__ import annotations

import pytest

from app.models.enums import SignalAction, SignalComponentKind
from app.signals.fusion import ComponentScore, fuse

TECH = SignalComponentKind.TECHNICAL
LGBM = SignalComponentKind.LIGHTGBM


def component(kind=TECH, score=0.5, weight=1.0, confidence=1.0, active=True, version="v1"):
    return ComponentScore(kind=kind, score=score, weight=weight, confidence=confidence,
                          version=version, active=active)


class TestNoValidSetup:
    def test_no_components_at_all_is_no_valid_setup(self):
        result = fuse([], min_confidence=0.3, action_margin=0.1)
        assert result.action is SignalAction.NO_VALID_SETUP
        assert result.confidence == 0.0

    def test_all_components_inactive_is_no_valid_setup(self):
        result = fuse(
            [component(active=False), component(kind=LGBM, active=False)],
            min_confidence=0.3, action_margin=0.1,
        )
        assert result.action is SignalAction.NO_VALID_SETUP
        assert "NO_ACTIVE_COMPONENTS" in result.reason_codes

    def test_zero_total_weight_is_no_valid_setup_not_a_crash(self):
        result = fuse([component(weight=0.0)], min_confidence=0.3, action_margin=0.1)
        assert result.action is SignalAction.NO_VALID_SETUP


class TestConfidenceGate:
    def test_low_confidence_waits_even_with_a_strong_directional_score(self):
        result = fuse(
            [component(score=0.95, confidence=0.1)], min_confidence=0.3, action_margin=0.1
        )
        assert result.action is SignalAction.WAIT
        assert "LOW_CONFIDENCE" in result.reason_codes

    def test_confidence_exactly_at_the_threshold_passes(self):
        result = fuse(
            [component(score=0.9, confidence=0.3)], min_confidence=0.3, action_margin=0.1
        )
        assert result.action is not SignalAction.WAIT or "LOW_CONFIDENCE" not in result.reason_codes


class TestActionMargin:
    def test_a_score_too_close_to_neutral_waits(self):
        result = fuse(
            [component(score=0.55, confidence=1.0)], min_confidence=0.3, action_margin=0.1
        )
        assert result.action is SignalAction.WAIT
        assert "NEAR_NEUTRAL" in result.reason_codes

    def test_a_score_beyond_the_margin_buys(self):
        result = fuse(
            [component(score=0.65, confidence=1.0)], min_confidence=0.3, action_margin=0.1
        )
        assert result.action is SignalAction.BUY

    def test_a_score_beyond_the_margin_bearish_sells(self):
        result = fuse(
            [component(score=0.35, confidence=1.0)], min_confidence=0.3, action_margin=0.1
        )
        assert result.action is SignalAction.SELL


class TestWeightedCombination:
    def test_equal_weights_average_the_scores(self):
        result = fuse(
            [component(TECH, score=0.6, weight=1.0), component(LGBM, score=0.8, weight=1.0)],
            min_confidence=0.0, action_margin=0.0,
        )
        assert result.score == pytest.approx(0.7)

    def test_a_heavier_weight_dominates_the_fused_score(self):
        result = fuse(
            [component(TECH, score=0.5, weight=1.0), component(LGBM, score=1.0, weight=9.0)],
            min_confidence=0.0, action_margin=0.0,
        )
        assert result.score == pytest.approx(0.95)

    def test_an_inactive_component_is_excluded_not_treated_as_neutral(self):
        """An absent LightGBM prediction must not silently drag a strongly
        bullish technical read toward the middle -- it should be renormalised
        away, since 'no opinion' is not the same as 'a neutral opinion'."""
        without_lgbm = fuse(
            [
                component(TECH, score=0.9, weight=0.4),
                component(LGBM, score=0.5, weight=0.6, active=False),
            ],
            min_confidence=0.0, action_margin=0.0,
        )
        assert without_lgbm.score == pytest.approx(0.9)

    def test_confidence_is_also_weighted(self):
        result = fuse(
            [
                component(TECH, score=0.9, weight=1.0, confidence=0.2),
                component(LGBM, score=0.9, weight=1.0, confidence=0.8),
            ],
            min_confidence=0.0, action_margin=0.0,
        )
        assert result.confidence == pytest.approx(0.5)


class TestReasonCodes:
    def test_reason_codes_name_each_active_components_lean(self):
        result = fuse(
            [
                component(TECH, score=0.9, confidence=1.0),
                component(LGBM, score=0.1, confidence=1.0),
            ],
            min_confidence=0.0, action_margin=0.0,
        )
        assert "COMPONENT_TECHNICAL_BULLISH" in result.reason_codes
        assert "COMPONENT_LIGHTGBM_BEARISH" in result.reason_codes

    def test_the_threshold_reason_leads_the_list(self):
        result = fuse([component(score=0.9, confidence=1.0)], min_confidence=0.3, action_margin=0.1)
        assert result.reason_codes[0] == "THRESHOLD_BUY"

    def test_inactive_components_are_still_returned_for_the_audit_trail(self):
        """§79/§80: the full decision chain is recorded, including what was
        available but not used."""
        inactive = component(LGBM, active=False)
        result = fuse([component(TECH), inactive], min_confidence=0.0, action_margin=0.0)
        assert inactive in result.components
