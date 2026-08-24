"""ORM model package.

Importing this package registers every table on ``Base.metadata`` — Alembic's
autogenerate and the integration test suite both depend on that.
"""

from app.models.backtesting import BacktestRun, BacktestTrade
from app.models.enums import (
    ComponentHealth,
    EngineState,
    ExecutionVenue,
    JobStatus,
    MarketRegimeState,
    ModelStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionStatus,
    RiskDecision,
    SignalAction,
    SignalComponentKind,
    TradeLifecycleState,
)
from app.models.market import (
    Candle,
    MarketDataMetadata,
    MarketRegime,
    Pattern,
    PatternStatistic,
    TechnicalFeature,
)
from app.models.ml import ModelMetric, ModelPrediction, ModelVersion, TrainingRun
from app.models.news import MacroEvent, NewsArticle, SentimentScore
from app.models.system import Asset, AuditLog, ExchangeSetting, SystemEvent, SystemSetting
from app.models.trading import (
    ExecutionEvent,
    LiveOrder,
    LivePosition,
    PaperOrder,
    PaperPosition,
    PortfolioSnapshot,
    RiskEvent,
    Signal,
    SignalComponent,
    Trade,
)

__all__ = [
    "Asset",
    "AuditLog",
    "BacktestRun",
    "BacktestTrade",
    "Candle",
    "ComponentHealth",
    "EngineState",
    "ExchangeSetting",
    "ExecutionEvent",
    "ExecutionVenue",
    "JobStatus",
    "LiveOrder",
    "LivePosition",
    "MacroEvent",
    "MarketDataMetadata",
    "MarketRegime",
    "MarketRegimeState",
    "ModelMetric",
    "ModelPrediction",
    "ModelStatus",
    "ModelVersion",
    "NewsArticle",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "PaperOrder",
    "PaperPosition",
    "Pattern",
    "PatternStatistic",
    "PortfolioSnapshot",
    "PositionStatus",
    "RiskDecision",
    "RiskEvent",
    "SentimentScore",
    "Signal",
    "SignalAction",
    "SignalComponent",
    "SignalComponentKind",
    "SystemEvent",
    "SystemSetting",
    "TechnicalFeature",
    "Trade",
    "TradeLifecycleState",
    "TrainingRun",
]
