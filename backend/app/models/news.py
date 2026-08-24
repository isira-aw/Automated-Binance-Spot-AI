"""News / macro / sentiment tables (§27, §28) — Tier 2.

The schema exists from Phase 1 so migrations stay linear, but nothing writes to
these tables until the Tier 2 news engine is built (§96).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin


class NewsArticle(Base, TimestampMixin):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    category: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_news_articles_provider"),
    )


class MacroEvent(Base, TimestampMixin):
    __tablename__ = "macro_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float | None] = mapped_column(Numeric(6, 4))
    actual: Mapped[str | None] = mapped_column(String(64))
    forecast: Mapped[str | None] = mapped_column(String(64))
    previous: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class SentimentScore(Base):
    """Structured LLM output for an article (§28), Pydantic-validated on write."""

    __tablename__ = "sentiment_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int | None] = mapped_column(Integer, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(128))
    # Normalised to the unified [0,1] fusion scale (§30a).
    sentiment: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    impact: Mapped[float | None] = mapped_column(Numeric(6, 4))
    importance: Mapped[float | None] = mapped_column(Numeric(6, 4))
    confidence: Mapped[float | None] = mapped_column(Numeric(6, 4))
    event_type: Mapped[str | None] = mapped_column(String(64))
    duration_estimate: Mapped[str | None] = mapped_column(String(32))

    __table_args__ = (
        Index("ix_sentiment_scores_symbol_time", "symbol", "computed_at"),
    )
