"""Structured application configuration (MASTER PROMPT §64, §65).

Settings are grouped into nested models rather than scattered constants.
Environment variables use ``__`` as the nested delimiter, e.g.
``BINANCE__TESTNET=true``; the flat aliases documented in ``.env.example``
are also honoured.
"""

from __future__ import annotations

import functools
import json
import os
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.config.risk_config import RiskConfig

# Repository root:  <root>/backend/app/config/settings.py -> parents[3].
# In a container the source tree is not laid out that way, so the root of the
# persistent volumes is supplied explicitly via APP_PROJECT_ROOT.
PROJECT_ROOT = Path(
    os.environ.get("APP_PROJECT_ROOT") or Path(__file__).resolve().parents[3]
).resolve()


def _strip_line_endings(data: object) -> object:
    """Trim stray CR/LF from raw environment values.

    Windows is the primary development machine (§67) and `.env` is produced by
    copying `.env.example`, so the file routinely has CRLF endings.  Docker
    Compose passes the trailing \r through as part of the value, which turns
    `BINANCE_TESTNET=true` into `'true\r'` -- not a valid boolean -- and takes
    the whole application down at import.  Only line endings are removed; other
    whitespace is left intact in case a value legitimately contains it.
    """
    if not isinstance(data, dict):
        return data
    return {
        key: value.strip("\r\n") if isinstance(value, str) else value
        for key, value in data.items()
    }


def _parse_str_list(value: object) -> object:
    """Accept both `a,b` and `["a","b"]` for a list field supplied via env.

    Flat environment variables are the documented form (see .env.example), but
    a JSON array is what pydantic-settings would natively expect, so both are
    honoured rather than silently mangling one of them.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.startswith("["):
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(decoded, list):
                return [str(item).strip() for item in decoded]
    return [item.strip() for item in text.split(",") if item.strip()]


class EnvModel(BaseSettings):
    """Base for nested config sections that read flat environment variables.

    A plain ``BaseModel`` nested inside ``BaseSettings`` does NOT consult the
    environment for its own fields -- ``validation_alias`` on such a field is
    only honoured for explicitly-passed data.  Sections therefore have to be
    settings sources in their own right, or documented variables like
    ``POSTGRES_PASSWORD`` are silently ignored in favour of the default.
    """

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _trim_line_endings(cls, data: object) -> object:
        return _strip_line_endings(data)


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PAPER = "paper"
    PRODUCTION = "production"


class TradingMode(str, Enum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    BINANCE_TESTNET = "BINANCE_TESTNET"
    LIVE = "LIVE"


class Timeframe(str, Enum):
    """Multi-timeframe system (§16)."""

    D1 = "1d"
    H4 = "4h"
    H1 = "1h"
    M15 = "15m"


class PathsConfig(BaseModel):
    """Persistent storage that lives outside the containers (§4)."""

    root: Path = PROJECT_ROOT
    data: Path = PROJECT_ROOT / "data"
    models: Path = PROJECT_ROOT / "models"
    artifacts: Path = PROJECT_ROOT / "artifacts"
    logs: Path = PROJECT_ROOT / "logs"
    backups: Path = PROJECT_ROOT / "backups"

    @property
    def models_production(self) -> Path:
        return self.models / "production"

    @property
    def models_candidates(self) -> Path:
        return self.models / "candidates"

    @property
    def models_archive(self) -> Path:
        return self.models / "archive"

    def ensure(self) -> None:
        for path in (
            self.data,
            self.data / "market",
            self.data / "news",
            self.data / "cache",
            self.models_production,
            self.models_candidates,
            self.models_archive,
            self.artifacts / "backtests",
            self.artifacts / "reports",
            self.artifacts / "metrics",
            self.logs,
            self.backups,
        ):
            path.mkdir(parents=True, exist_ok=True)


class DatabaseConfig(EnvModel):
    model_config = ConfigDict(populate_by_name=True)

    user: str = Field(default="trader", validation_alias=AliasChoices("POSTGRES_USER"))
    password: str = Field(
        default="trader", validation_alias=AliasChoices("POSTGRES_PASSWORD")
    )
    db: str = Field(
        default="binance_spot_ai", validation_alias=AliasChoices("POSTGRES_DB")
    )
    host: str = Field(default="postgres", validation_alias=AliasChoices("POSTGRES_HOST"))
    port: int = Field(default=5432, validation_alias=AliasChoices("POSTGRES_PORT"))
    pool_size: int = 10
    max_overflow: int = 5
    echo: bool = False

    def url(self, *, driver: str = "asyncpg") -> str:
        # Credentials are percent-encoded: a password containing @ : / # or %
        # would otherwise corrupt the URL and be parsed as host/port garbage.
        user = quote(self.user, safe="")
        password = quote(self.password, safe="")
        return (
            f"postgresql+{driver}://{user}:{password}"
            f"@{self.host}:{self.port}/{self.db}"
        )

    @property
    def async_url(self) -> str:
        return self.url(driver="asyncpg")

    @property
    def sync_url(self) -> str:
        return self.url(driver="psycopg")


class RedisConfig(EnvModel):
    model_config = ConfigDict(populate_by_name=True)

    host: str = Field(default="redis", validation_alias=AliasChoices("REDIS_HOST"))
    port: int = Field(default=6379, validation_alias=AliasChoices("REDIS_PORT"))
    db: int = Field(default=0, validation_alias=AliasChoices("REDIS_DB"))

    @property
    def url(self) -> str:
        return f"redis://{self.host}:{self.port}/{self.db}"


class BinanceConfig(EnvModel):
    """Binance Spot only.  No futures, no margin, no withdrawals (§9, §70)."""
    model_config = ConfigDict(populate_by_name=True)


    api_key: str = Field(default="", validation_alias=AliasChoices("BINANCE_API_KEY"))
    api_secret: str = Field(
        default="", validation_alias=AliasChoices("BINANCE_API_SECRET")
    )
    testnet: bool = Field(default=True, validation_alias=AliasChoices("BINANCE_TESTNET"))
    rest_timeout_seconds: float = 10.0
    recv_window_ms: int = 5000
    # Real rate limits are read from live `exchangeInfo` at runtime (§71).  These
    # are conservative client-side fallbacks used only before metadata loads.
    fallback_request_weight_per_minute: int = 1000
    fallback_orders_per_second: int = 5
    max_retries: int = 4
    retry_backoff_seconds: float = 2.0

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)


class TradingConfig(EnvModel):
    model_config = ConfigDict(populate_by_name=True)

    # NoDecode on both lists for the same reason as cors_allow_origins: a flat
    # env var supplies a comma-separated string, not JSON.
    assets: Annotated[list[str], NoDecode] = Field(
        default=["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    )
    timeframes: Annotated[list[Timeframe], NoDecode] = Field(
        default=[Timeframe.D1, Timeframe.H4, Timeframe.H1, Timeframe.M15]
    )
    decision_timeframe: Timeframe = Timeframe.H4
    entry_timeframe: Timeframe = Timeframe.M15
    mode: TradingMode = Field(
        default=TradingMode.PAPER, validation_alias=AliasChoices("TRADING_MODE")
    )
    live_trading_enabled: bool = Field(
        default=False, validation_alias=AliasChoices("LIVE_TRADING_ENABLED")
    )
    minimum_confidence: float = Field(default=0.62, ge=0.0, le=1.0)
    maker_fee: float = 0.001
    taker_fee: float = 0.001

    @field_validator("assets", "timeframes", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        return _parse_str_list(value)

    @field_validator("assets")
    @classmethod
    def _uppercase(cls, value: list[str]) -> list[str]:
        return [item.strip().upper() for item in value if item.strip()]


class PaperTradingConfig(BaseModel):
    initial_balance: float = 50.0
    quote_asset: str = "USDT"
    simulated_latency_ms: int = 250
    slippage_bps: float = 5.0
    allow_partial_fills: bool = True


class BacktestConfig(BaseModel):
    initial_capital: float = 50.0
    maker_fee: float = 0.001
    taker_fee: float = 0.001
    slippage_bps: float = 5.0


class ModelsConfig(BaseModel):
    """Tier 1 is LightGBM only; Transformer/ensemble are Tier 2 (§1a, §25)."""

    lightgbm_enabled: bool = True
    transformer_enabled: bool = False
    ensemble_enabled: bool = False
    feature_version: str = "v1"
    strategy_version: str = "v1"

    # --- LightGBM training (§24, §36, §37) ---------------------------------
    # Forward-return horizon (in candles) and the neutral-band threshold the
    # label is built from (app/ml/labeling.py) — not a claim these values are
    # tuned, only a documented, versioned starting point for the baseline.
    label_horizon: int = Field(default=4, ge=1)
    label_threshold: float = Field(default=0.003, ge=0.0)
    train_fraction: float = Field(default=0.7, gt=0.0, lt=1.0)
    validation_fraction: float = Field(default=0.15, gt=0.0, lt=1.0)
    # Below this, a candidate is kept (never deleted, §39) but not promoted to
    # VALIDATED. 0.34 is barely above the ~0.33 baseline of guessing among
    # three classes — deliberately unambitious: promotion to PRODUCTION still
    # requires a backtest (Phase 12) this system does not have yet, so this
    # bar only gates "is this candidate worth a human looking at."
    min_validation_accuracy: float = Field(default=0.34, ge=0.0, le=1.0)
    min_validation_macro_f1: float = Field(default=0.25, ge=0.0, le=1.0)
    min_training_rows: int = Field(default=500, ge=1)

    # --- Signal fusion (§30) -----------------------------------------------
    # Tier 1 fuses exactly two components; Tier 2 (pattern, regime,
    # transformer, news, fundamental, local LLM, Claude) stay inactive until
    # their own phases build them.  Weights are the versioned combination
    # method §30b requires be specified, not "figure it out later" -- changing
    # them is a strategy_version change, not a silent behavioural drift.
    technical_component_weight: float = Field(default=0.4, ge=0.0)
    lightgbm_component_weight: float = Field(default=0.6, ge=0.0)
    # A signal below this confidence is WAIT, never a forced guess (§86).
    fusion_min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    # How far from neutral (0.5) the fused score must sit to imply a
    # direction at all, before the confidence gate is even considered.
    fusion_action_margin: float = Field(default=0.1, ge=0.0, le=0.5)


class LLMConfig(EnvModel):
    """Tier 2 — disabled by default; Tier 1 runs without it (§6, §7, §8)."""
    model_config = ConfigDict(populate_by_name=True)


    ollama_enabled: bool = Field(
        default=False, validation_alias=AliasChoices("OLLAMA_ENABLED")
    )
    ollama_base_url: str = Field(
        default="", validation_alias=AliasChoices("OLLAMA_BASE_URL")
    )
    ollama_model: str = Field(default="", validation_alias=AliasChoices("OLLAMA_MODEL"))
    ollama_timeout_seconds: float = Field(
        default=8.0, validation_alias=AliasChoices("OLLAMA_TIMEOUT_SECONDS")
    )
    claude_enabled: bool = Field(
        default=False, validation_alias=AliasChoices("CLAUDE_ENABLED")
    )
    claude_api_key: str = Field(
        default="", validation_alias=AliasChoices("CLAUDE_API_KEY")
    )
    claude_max_calls_per_day: int = Field(
        default=50, validation_alias=AliasChoices("CLAUDE_MAX_CALLS_PER_DAY")
    )


class NewsConfig(EnvModel):
    """Tier 2 — disabled by default (§27)."""
    model_config = ConfigDict(populate_by_name=True)


    enabled: bool = Field(default=False, validation_alias=AliasChoices("NEWS_ENABLED"))
    poll_interval_seconds: int = 900


class WebSocketConfig(BaseModel):
    heartbeat_interval_seconds: float = 20.0
    client_timeout_seconds: float = 60.0
    outbound_queue_size: int = 500
    max_connections: int = 32


class Settings(BaseSettings):
    """Root settings object.  Access it via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Automated Binance Spot AI"
    api_v1_prefix: str = "/api/v1"
    env: AppEnv = Field(
        default=AppEnv.DEVELOPMENT, validation_alias=AliasChoices("APP_ENV")
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", validation_alias=AliasChoices("LOG_LEVEL")
    )
    api_host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("API_HOST"))
    api_port: int = Field(default=8000, validation_alias=AliasChoices("API_PORT"))
    # NoDecode: the env source would otherwise json.loads() this value and
    # raise before the splitter below sees the comma-separated form.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:5173"],
        validation_alias=AliasChoices("CORS_ALLOW_ORIGINS"),
    )

    paths: PathsConfig = PathsConfig()
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    binance: BinanceConfig = Field(default_factory=BinanceConfig)
    trading: TradingConfig = Field(default_factory=TradingConfig)
    risk: RiskConfig = RiskConfig()
    paper_trading: PaperTradingConfig = PaperTradingConfig()
    backtesting: BacktestConfig = BacktestConfig()
    models: ModelsConfig = ModelsConfig()
    llm: LLMConfig = Field(default_factory=LLMConfig)
    news: NewsConfig = Field(default_factory=NewsConfig)
    websocket: WebSocketConfig = WebSocketConfig()

    @model_validator(mode="before")
    @classmethod
    def _trim_line_endings(cls, data: object) -> object:
        return _strip_line_endings(data)

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        return _parse_str_list(value)

    @property
    def is_production(self) -> bool:
        return self.env is AppEnv.PRODUCTION

    @property
    def docs_enabled(self) -> bool:
        """Swagger is a development affordance (§108)."""
        return not self.is_production

    def validate_environment(self) -> list[str]:
        """Return blocking configuration errors (§65, §99).

        Production must never accidentally enable live trading, and must never
        run behind a wildcard CORS policy.
        """
        problems: list[str] = []
        if "*" in self.cors_allow_origins and self.is_production:
            problems.append(
                "CORS_ALLOW_ORIGINS must be an explicit allow-list in production."
            )
        if (
            self.trading.mode is TradingMode.LIVE
            and not self.trading.live_trading_enabled
        ):
            problems.append(
                "TRADING_MODE=LIVE requires LIVE_TRADING_ENABLED=true and an "
                "explicit ARM action; refusing to start in LIVE."
            )
        if self.trading.live_trading_enabled and not self.binance.has_credentials:
            problems.append(
                "Live trading is enabled but Binance credentials are unset."
            )
        return problems


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
