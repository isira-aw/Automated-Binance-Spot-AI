"""Domain enumerations shared by ORM models and API schemas."""

from __future__ import annotations

from enum import Enum


class SignalAction(str, Enum):
    """Valid signal outcomes (§54).  `WAIT` is a first-class result."""

    BUY = "BUY"
    SELL = "SELL"
    EXIT = "EXIT"
    WAIT = "WAIT"
    NO_VALID_SETUP = "NO_VALID_SETUP"


class RiskDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAUSED = "PAUSED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class TradeLifecycleState(str, Enum):
    """Trade lifecycle (§34)."""

    SCAN = "SCAN"
    ANALYZE = "ANALYZE"
    WAIT = "WAIT"
    SIGNAL = "SIGNAL"
    RISK_CHECK = "RISK_CHECK"
    ORDER = "ORDER"
    FILL = "FILL"
    POSITION = "POSITION"
    MONITOR = "MONITOR"
    EXIT = "EXIT"
    CLOSE = "CLOSE"
    COOLDOWN = "COOLDOWN"
    POST_TRADE_ANALYSIS = "POST_TRADE_ANALYSIS"


class MarketRegimeState(str, Enum):
    """Market regime engine states (§23) — Tier 2."""

    TRENDING_BULL = "TRENDING_BULL"
    TRENDING_BEAR = "TRENDING_BEAR"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    CRASH = "CRASH"
    RECOVERY = "RECOVERY"
    UNCERTAIN = "UNCERTAIN"


class ModelStatus(str, Enum):
    """Model registry states (§39)."""

    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    PRODUCTION = "PRODUCTION"
    ARCHIVED = "ARCHIVED"
    REJECTED = "REJECTED"


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EngineState(str, Enum):
    """Trading engine states (§45)."""

    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class ComponentHealth(str, Enum):
    """System monitoring status values (§43)."""

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    DISABLED = "DISABLED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class SignalComponentKind(str, Enum):
    """Signal fusion inputs (§30).  Tier 2 kinds exist but stay inactive."""

    TECHNICAL = "TECHNICAL"
    PATTERN = "PATTERN"
    REGIME = "REGIME"
    LIGHTGBM = "LIGHTGBM"
    TRANSFORMER = "TRANSFORMER"
    NEWS = "NEWS"
    FUNDAMENTAL = "FUNDAMENTAL"
    LOCAL_LLM = "LOCAL_LLM"
    CLAUDE = "CLAUDE"


class ExecutionVenue(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    BINANCE_TESTNET = "BINANCE_TESTNET"
    LIVE = "LIVE"
