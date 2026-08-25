"""Maps a technical-features row to the unified [0,1] fusion scale (§30a).

This is the "documented, versioned mapping function" §30a requires for any
component whose native output is not already a class probability -- the
technical indicator/structure vector has no single natural score, so one is
built here explicitly, once, rather than left to whichever caller needs it.

Design: several independent sub-signals, each already scaled to [-1, 1]
(bearish .. bullish), averaged into a raw score, then rescaled to [0, 1] via
``(raw + 1) / 2`` -- the same rescaling §30a's own LightGBM example uses, so
every component that isn't natively a probability follows one convention.

A sub-signal whose input is ``None`` (an indicator that has not cleared its
own warm-up window, per Phase 7's "store the row, leave the field null"
design) contributes nothing rather than a fabricated neutral guess -- it is
excluded from the average, not silently coerced to 0. Confidence reflects
this: fewer available sub-signals and less agreement between them both pull
confidence down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TECHNICAL_SCORE_VERSION = "v1"


@dataclass(frozen=True)
class SubSignal:
    name: str
    value: float | None  # already in [-1, 1], or None if unavailable


def _trend_subsignal(features: dict[str, Any]) -> SubSignal:
    """SMA20 vs SMA50 crossover, scaled by distance relative to price."""
    sma_20, sma_50 = features.get("sma_20"), features.get("sma_50")
    if sma_20 is None or sma_50 is None or sma_50 == 0:
        return SubSignal("trend", None)
    spread = (sma_20 - sma_50) / sma_50
    # A 2% spread is treated as a fully-formed trend signal; beyond that adds
    # no further conviction, which keeps one outlier bar from dominating.
    return SubSignal("trend", max(-1.0, min(1.0, spread / 0.02)))


def _momentum_subsignal(features: dict[str, Any]) -> SubSignal:
    """RSI centred at 50, plus MACD histogram sign, averaged."""
    parts: list[float] = []
    rsi = features.get("rsi_14")
    if rsi is not None:
        parts.append(max(-1.0, min(1.0, (rsi - 50.0) / 50.0)))
    histogram = features.get("macd_histogram")
    macd_line = features.get("macd")
    if histogram is not None and macd_line is not None and macd_line != 0:
        parts.append(max(-1.0, min(1.0, histogram / abs(macd_line))))
    if not parts:
        return SubSignal("momentum", None)
    return SubSignal("momentum", sum(parts) / len(parts))


def _directional_movement_subsignal(features: dict[str, Any]) -> SubSignal:
    """+DI vs -DI, weighted by ADX (trend strength)."""
    plus_di, minus_di, adx = features.get("plus_di"), features.get("minus_di"), features.get("adx")
    if plus_di is None or minus_di is None:
        return SubSignal("directional_movement", None)
    total = plus_di + minus_di
    if total == 0:
        return SubSignal("directional_movement", 0.0)
    raw = (plus_di - minus_di) / total
    strength = 1.0 if adx is None else max(0.0, min(1.0, adx / 40.0))
    return SubSignal("directional_movement", raw * strength)


def _structure_subsignal(features: dict[str, Any]) -> SubSignal:
    """Market structure trend and this bar's HH/HL/LH/LL events (§20)."""
    trend = features.get("structure_trend")
    base = {"BULLISH": 1.0, "BEARISH": -1.0}.get(trend, 0.0) if trend is not None else None

    event = 0.0
    if features.get("is_higher_high") or features.get("is_higher_low"):
        event += 0.5
    if features.get("is_lower_high") or features.get("is_lower_low"):
        event -= 0.5
    if features.get("break_of_structure"):
        event += 0.5 if base and base > 0 else (-0.5 if base and base < 0 else 0.0)
    if features.get("false_breakout"):
        # A breakout that failed argues against the direction it broke in.
        event -= 0.3 if features.get("breakout") else 0.0
        event += 0.3 if features.get("breakdown") else 0.0

    if base is None and event == 0.0:
        return SubSignal("structure", None)
    combined = (base or 0.0) + event
    return SubSignal("structure", max(-1.0, min(1.0, combined)))


def _volatility_confidence_penalty(features: dict[str, Any]) -> float:
    """Extreme volatility widens the error bars on every other sub-signal.

    Returns a multiplier in (0, 1]; never amplifies confidence, only caps it.
    """
    percentile = features.get("volatility_percentile_100")
    if percentile is None:
        return 1.0
    # Above the 90th percentile of its own recent range, halve confidence
    # linearly down to the extreme.
    if percentile <= 0.9:
        return 1.0
    return max(0.5, 1.0 - (percentile - 0.9) * 5.0)


def compute_technical_score(features: dict[str, Any]) -> tuple[float, float, dict[str, Any]]:
    """Return ``(score, confidence, details)`` on the [0, 1] fusion scale.

    ``details`` records each sub-signal's raw value for the audit trail
    (§47, §81) -- an operator asking "why did technical say bullish" gets a
    real breakdown, not just the final number.
    """
    subsignals = [
        _trend_subsignal(features),
        _momentum_subsignal(features),
        _directional_movement_subsignal(features),
        _structure_subsignal(features),
    ]
    available = [s for s in subsignals if s.value is not None]

    details: dict[str, Any] = {
        "version": TECHNICAL_SCORE_VERSION,
        "subsignals": {s.name: s.value for s in subsignals},
        "available_count": len(available),
    }

    if not available:
        # Nothing to go on: neutral score, zero confidence -- never a guess.
        return 0.5, 0.0, details

    raw = sum(s.value for s in available) / len(available)
    score = (raw + 1.0) / 2.0

    # Confidence blends how strongly the available sub-signals lean with how
    # many of them are available at all, then is capped by volatility.
    completeness = len(available) / len(subsignals)
    conviction = abs(raw)
    confidence = conviction * completeness * _volatility_confidence_penalty(features)

    details["raw_score"] = raw
    details["completeness"] = completeness

    return max(0.0, min(1.0, score)), max(0.0, min(1.0, confidence)), details
