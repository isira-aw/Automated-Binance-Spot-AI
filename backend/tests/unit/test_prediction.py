"""Fusion score mapping and prediction-layer guards (§26, §30a)."""

from __future__ import annotations

import numpy as np
import pytest

from app.ml.prediction import confidence_from_probabilities, fusion_score_from_probabilities


class TestFusionScoreMapping:
    """§30a's documented example mapping: P(up) - P(down) rescaled to [0,1]."""

    def test_certain_up_maps_to_one(self):
        assert fusion_score_from_probabilities(prob_up=1.0, prob_down=0.0) == pytest.approx(1.0)

    def test_certain_down_maps_to_zero(self):
        assert fusion_score_from_probabilities(prob_up=0.0, prob_down=1.0) == pytest.approx(0.0)

    def test_balanced_probabilities_map_to_neutral_half(self):
        assert fusion_score_from_probabilities(prob_up=0.4, prob_down=0.4) == pytest.approx(0.5)

    def test_all_neutral_maps_to_half(self):
        assert fusion_score_from_probabilities(prob_up=0.0, prob_down=0.0) == pytest.approx(0.5)

    @pytest.mark.parametrize(
        ("prob_up", "prob_down"),
        [(0.9, 0.05), (0.6, 0.3), (0.1, 0.1), (0.0, 0.9), (0.5, 0.5)],
    )
    def test_result_is_always_in_unit_interval(self, prob_up, prob_down):
        result = fusion_score_from_probabilities(prob_up, prob_down)
        assert 0.0 <= result <= 1.0

    def test_above_half_leans_bullish_below_half_leans_bearish(self):
        """Matches §30a's scale definition directly."""
        bullish = fusion_score_from_probabilities(prob_up=0.6, prob_down=0.2)
        bearish = fusion_score_from_probabilities(prob_up=0.2, prob_down=0.6)
        assert bullish > 0.5
        assert bearish < 0.5


class TestConfidence:
    def test_confidence_is_the_top_class_probability(self):
        row = np.array([0.1, 0.2, 0.7])
        assert confidence_from_probabilities(row) == pytest.approx(0.7)

    def test_confidence_is_symmetric_between_up_and_down_calls(self):
        """A confident DOWN call and a confident UP call carry the same
        confidence -- direction lives in fusion_score, not here."""
        confident_up = np.array([0.05, 0.05, 0.9])
        confident_down = np.array([0.9, 0.05, 0.05])
        assert confidence_from_probabilities(confident_up) == confidence_from_probabilities(
            confident_down
        )

    def test_uniform_probabilities_have_low_confidence(self):
        row = np.array([1 / 3, 1 / 3, 1 / 3])
        assert confidence_from_probabilities(row) == pytest.approx(1 / 3)
