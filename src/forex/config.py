"""Load and validate the single operator configuration and environment secrets."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
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
