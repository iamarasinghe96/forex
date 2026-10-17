"""Strategy-lab settings (``strategy-lab.yaml``): data, costs, the paper rules and each strategy."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_FILE = Path("strategy-lab.yaml")


class Rules(BaseModel):
    """The paper bot's trade rules (config.yaml), applied to every simulated trade."""

    model_config = ConfigDict(extra="forbid")
    risk_percent: float = Field(default=5.0, gt=0, le=100)
    starting_balance_aud: float = Field(default=1000.0, gt=0)
    one_trade_per_pair: bool = True
    usd_cap_percent: float | None = Field(default=10.0, gt=0)
    breakeven_at_r: float | None = Field(default=1.0, gt=0)
    trail_atr: float | None = Field(default=3.0, gt=0)
    target_r: float | None = Field(default=10.0, gt=0)
    max_hours: int | None = Field(default=None, gt=0)        # Time exit; null = none, as live.
    max_hold_hours: int = Field(default=720, gt=0)          # Safety limit for trades that never exit.


class DataSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    databases: list[Path] = [Path("data/dukascopy-2012-2018.sqlite3"), Path("data/dukascopy-research.sqlite3"),
                             Path("data/rebuilt/dukascopy-2012-2018.sqlite3"),
                             Path("data/rebuilt/dukascopy-research.sqlite3")]
    fallback_databases: list[Path] = [Path("data/paper-a1000.sqlite3")]
    pairs: list[str] = ["EURUSD", "GBPUSD", "USDJPY"]
    start: date = date(2012, 4, 1)
    end: date | None = None
    split_year: int = 2019


class StrategyEntry(BaseModel):
    """``enabled`` and ``exits`` (rule overrides); any other key is a strategy parameter."""

    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    exits: dict[str, Any] = {}

    def parameters(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class LabSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    data: DataSettings = DataSettings()
    costs_pips: dict[str, float] = {"EURUSD": 0.9, "GBPUSD": 1.2, "USDJPY": 1.0}
    rules: Rules = Rules()
    random_runs: int = Field(default=200, ge=0)
    random_seed: int = 20261017
    workers: int = Field(default=3, ge=1)
    min_trades: int = Field(default=100, ge=1)
    strategies: dict[str, StrategyEntry] = {}


def load_settings(path: Path = DEFAULT_FILE) -> LabSettings:
    if not path.is_file():
        return LabSettings()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return LabSettings.model_validate(raw)
