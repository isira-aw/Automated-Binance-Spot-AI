"""Persisting risk decisions to ``risk_events`` (§31, §47).

Every blocking decision is recorded -- not only approvals -- because the
question an operator asks after a quiet day is "why didn't it trade?", and
that is unanswerable if rejections were never written down.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RiskDecision
from app.models.trading import RiskEvent
from app.risk.engine import RiskAssessment


async def record_risk_event(
    session: AsyncSession,
    assessment: RiskAssessment,
    *,
    symbol: str | None,
    venue: str = "PAPER",
    signal_id: int | None = None,
) -> RiskEvent | None:
    """Store a non-approval decision.  Returns None for APPROVED.

    Approvals are not written here: they become orders, and the order itself
    plus its ``execution_events`` row is the durable record of that path
    (§34).  Writing both would duplicate the same fact in two tables that
    could then disagree.
    """
    if assessment.decision is RiskDecision.APPROVED:
        return None

    event = RiskEvent(
        timestamp=assessment.assessed_at,
        venue=venue,
        symbol=symbol,
        decision=assessment.decision.value,
        rule=assessment.rule,
        reason=assessment.reason,
        signal_id=signal_id,
        details=assessment.details or None,
    )
    session.add(event)
    await session.commit()
    return event
