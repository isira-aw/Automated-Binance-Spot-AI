"""Combines component scores into BUY | SELL | WAIT | NO_VALID_SETUP (§30, §86).

Tier 1 fuses exactly two components: TECHNICAL and LIGHTGBM. Every other
:class:`SignalComponentKind` (pattern, regime, transformer, news,
fundamental, local LLM, Claude) is Tier 2 and simply does not appear in the
component list yet -- there is no placeholder score standing in for them.

The combination method is a configured weighted average, not an unweighted
"naive average" (§26, §30b's own caution against that): each component's
weight comes from :class:`ModelsConfig`, so a strategy change is a config
(and therefore ``strategy_version``) change, never a silent code change.
A component with no available score (e.g. no LightGBM model registered yet)
is dropped from the average and renormalised over what remains, rather than
penalised as if it had voted neutral -- an absent opinion is not the same as
an "I don't know" opinion, and should not be scored as one.

Confidence-weighted blending (§26) beyond this simple weighted average is
deferred: it needs the calibration check §85 requires, which needs real
predictions to calibrate against, which this system does not have yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import SignalAction, SignalComponentKind


@dataclass(frozen=True)
class ComponentScore:
    """One component's contribution, already on the [0, 1] fusion scale."""

    kind: SignalComponentKind
    score: float
    weight: float
    confidence: float
    version: str
    active: bool = True
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FusionResult:
    action: SignalAction
    score: float
    confidence: float
    reason_codes: list[str]
    components: list[ComponentScore]


def fuse(
    components: list[ComponentScore],
    *,
    min_confidence: float,
    action_margin: float,
) -> FusionResult:
    """Combine ``components`` into a single decision.

    Threshold order matches §86: no active input at all is
    ``NO_VALID_SETUP`` (not the same as a merely low-confidence WAIT --
    there was nothing to evaluate); insufficient confidence is ``WAIT``;
    a fused score too close to neutral to imply a direction is ``WAIT``;
    otherwise the sign of the score decides BUY vs SELL.
    """
    active = [c for c in components if c.active]
    reason_codes: list[str] = []

    if not active:
        return FusionResult(
            action=SignalAction.NO_VALID_SETUP,
            score=0.5,
            confidence=0.0,
            reason_codes=["NO_ACTIVE_COMPONENTS"],
            components=components,
        )

    total_weight = sum(c.weight for c in active)
    if total_weight <= 0:
        return FusionResult(
            action=SignalAction.NO_VALID_SETUP,
            score=0.5,
            confidence=0.0,
            reason_codes=["ZERO_TOTAL_WEIGHT"],
            components=components,
        )

    fused_score = sum(c.score * c.weight for c in active) / total_weight
    fused_confidence = sum(c.confidence * c.weight for c in active) / total_weight

    for component in active:
        if component.score > 0.5:
            lean = "BULLISH"
        elif component.score < 0.5:
            lean = "BEARISH"
        else:
            lean = "NEUTRAL"
        reason_codes.append(f"COMPONENT_{component.kind.value}_{lean}")

    if fused_confidence < min_confidence:
        reason_codes.insert(0, "LOW_CONFIDENCE")
        return FusionResult(
            action=SignalAction.WAIT,
            score=fused_score,
            confidence=fused_confidence,
            reason_codes=reason_codes,
            components=components,
        )

    distance_from_neutral = fused_score - 0.5
    if abs(distance_from_neutral) < action_margin:
        reason_codes.insert(0, "NEAR_NEUTRAL")
        return FusionResult(
            action=SignalAction.WAIT,
            score=fused_score,
            confidence=fused_confidence,
            reason_codes=reason_codes,
            components=components,
        )

    action = SignalAction.BUY if distance_from_neutral > 0 else SignalAction.SELL
    reason_codes.insert(0, f"THRESHOLD_{action.value}")
    return FusionResult(
        action=action,
        score=fused_score,
        confidence=fused_confidence,
        reason_codes=reason_codes,
        components=components,
    )
