"""Load and validate the single operator configuration and environment secrets."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]  # Runtime dependency; dev stubs may be offline.
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from forex.errors import OperatorError


class Secrets(BaseSettings):
    """Secrets read from `.env`; their values are never included in representations."""

    model_config = SettingsConfigDict(
    env_file=".env",
    env_prefix="FOREX_",
    extra="ignore",
    validate_default=True,
)
    mt5_password: str = Field(default="", min_length=1, repr=False)
    telegram_bot_token: str = Field(default="", repr=False)
    telegram_chat_id: str = Field(default="", repr=False)


class BrokerConfig(BaseModel):
    login: int = Field(gt=0)
    server: str = Field(min_length=1)
    terminal_path: str | None = None
    account_currency: str = Field(pattern=r"^[A-Z]{3}$")
    symbols: list[str] = Field(min_length=1)
    magic_number: int = Field(gt=0)
    connect_timeout_seconds: int = Field(gt=0, le=300)


class LoggingConfig(BaseModel):
    directory: Path
    max_bytes: int = Field(gt=0)
    backup_count: int = Field(ge=1)


class DatabaseConfig(BaseModel):
    path: Path


class MarketDataConfig(BaseModel):
    stale_h1_hours: int = Field(default=3, gt=0)
    stale_h4_hours: int = Field(default=8, gt=0)
    weekend_close_weekday: int = Field(default=4, ge=0, le=6)
    weekend_close_hour_utc: int = Field(default=22, ge=0, le=23)
    weekend_open_weekday: int = Field(default=6, ge=0, le=6)
    weekend_open_hour_utc: int = Field(default=22, ge=0, le=23)
    history_chunk_days: int = Field(default=90, ge=7, le=366)
    history_retry_count: int = Field(default=3, ge=1, le=10)
    server_clock_tolerance_seconds: int = Field(default=300, gt=0, le=3600)


class AnalysisConfig(BaseModel):
    """UNVALIDATED Layer 3 research starting points; Layer 4 may vary every field."""

    strategy_version: str = "layer3-v1"
    parameter_version: str = "unvalidated-v1"
    ema_fast: int = Field(default=20, ge=2)
    ema_slow: int = Field(default=50, ge=3)
    ema_context: int = Field(default=200, ge=4)
    rsi_period: int = Field(default=14, ge=2)
    macd_fast: int = Field(default=12, ge=2)
    macd_slow: int = Field(default=26, ge=3)
    macd_signal: int = Field(default=9, ge=2)
    atr_period: int = Field(default=14, ge=2)
    structure_window: int = Field(default=20, ge=3)
    volatility_window: int = Field(default=100, ge=10)
    slope_lookback: int = Field(default=5, ge=1)
    return_horizons: list[int] = Field(default=[1, 5, 20], min_length=1)
    trend_threshold: float = Field(default=0.55, ge=0, le=1)
    range_threshold: float = Field(default=0.58, ge=0, le=1)
    setup_score_threshold: float = Field(default=0.45, ge=0, le=1)
    extreme_zscore: float = Field(default=1.0, gt=0)
    swing_trend_threshold: float = Field(default=0.68, ge=0, le=1)

    @model_validator(mode="after")
    def ordered_periods(self) -> AnalysisConfig:
        if not self.ema_fast < self.ema_slow < self.ema_context:
            raise ValueError("analysis EMA periods must satisfy fast < slow < context")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("analysis MACD fast period must be below slow period")
        return self


class BacktestConfig(BaseModel):
    """Explicit, UNVALIDATED Layer 4 research assumptions (never live execution)."""

    forward_horizons_bars: list[int] = Field(default=[6, 24, 120], min_length=1)
    simulation_horizon_bars: int = Field(default=120, ge=1)
    reward_risk: float = Field(default=1.5, ge=1.5)
    breakeven_at_r: float | None = Field(default=1.0, ge=0)
    atr_trailing_multiple: float | None = Field(default=None, gt=0)
    ambiguity_policy: Literal["adverse", "ambiguous"] = "adverse"
    minimum_history_years: float = Field(default=5.0, ge=5.0)
    monte_carlo_iterations: int = Field(default=1000, ge=1)
    monte_carlo_seed: int = 26092801
    train_days: int = Field(default=365 * 2, ge=1)
    test_days: int = Field(default=180, ge=1)
    step_days: int = Field(default=180, ge=1)
    final_holdout_days: int = Field(default=365, ge=0)
    report_directory: Path = Path("reports/backtest")

    @model_validator(mode="after")
    def valid_horizons(self) -> BacktestConfig:
        if any(value < 1 for value in self.forward_horizons_bars):
            raise ValueError("backtest forward horizons must be positive")
        if len(set(self.forward_horizons_bars)) != len(self.forward_horizons_bars):
            raise ValueError("backtest forward horizons must be unique")
        return self


class TelegramConfig(BaseModel):
    enabled: bool
    timeout_seconds: int = Field(gt=0, le=60)


class RiskConfig(BaseModel):
    max_leverage: int = Field(gt=0, le=30)
    minimum_reward_risk: float = Field(ge=1.5)
    max_concurrent_positions: int = Field(gt=0)
    max_simultaneous_risk_percent: float = Field(gt=0, le=20)
    daily_loss_percent: float = Field(gt=0)
    tax_reserve_percent: float = Field(ge=0, le=100)
    conviction_risk_percent: dict[str, float]
    target_trades_per_week: dict[str, int]


class AppConfig(BaseModel):
    mode: Literal["paper", "live"]
    operator_timezone: str
    broker: BrokerConfig
    logging: LoggingConfig
    database: DatabaseConfig
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    telegram: TelegramConfig
    risk: RiskConfig

    @model_validator(mode="after")
    def live_requires_deliberate_config(self) -> AppConfig:
        if self.mode == "live" and "Demo" in self.broker.server:
            raise ValueError("live mode cannot be paired with a demo server")
        return self


def load_config(path: Path) -> AppConfig:
    """Read YAML and return a validated configuration or actionable failure."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return AppConfig.model_validate(raw)
    except FileNotFoundError as exc:
        raise OperatorError(
            f"Configuration file {path} was not found. Copy config.yaml beside the command "
            "and run it again."
        ) from exc
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise OperatorError(
            f"Configuration {path} is invalid: {exc}. Correct the named setting in config.yaml."
        ) from exc
