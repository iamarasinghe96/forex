"""Stable broker-neutral types shared by live code and test doubles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class AccountMode(str, Enum):
    HEDGING = "hedging"
    NETTING = "netting"


@dataclass(frozen=True)
class AccountState:
    login: int
    currency: str
    balance: Decimal
    equity: Decimal
    leverage: int
    mode: AccountMode


@dataclass(frozen=True)
class Tick:
    symbol: str
    bid: Decimal
    ask: Decimal
    time_utc: datetime


@dataclass(frozen=True)
class SymbolSpec:
    requested_name: str
    broker_name: str
    base_currency: str
    profit_currency: str
    digits: int
    point: Decimal
    tick_size: Decimal
    tick_value: Decimal
    contract_size: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal
    stops_level_points: int
    freeze_level_points: int
    filling_mode: int

    @property
    def pip_size(self) -> Decimal:
        """Return a conventional pip derived from the broker's point and digits."""
        return self.point * (Decimal(10) if self.digits in (3, 5) else Decimal(1))
