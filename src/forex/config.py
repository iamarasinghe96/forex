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

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FOREX_", extra="ignore")
    mt5_password: str = Field(min_length=1, repr=False)
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
    telegram: TelegramConfig
    risk: RiskConfig

    @model_validator(mode="after")
    def live_requires_deliberate_config(self) -> "AppConfig":
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
