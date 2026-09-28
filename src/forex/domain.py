"""Stable broker-neutral types shared by live code and test doubles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum


class AccountMode(str, Enum):
    HEDGING = "hedging"
    NETTING = "netting"


class Timeframe(str, Enum):
    """Broker-neutral supported candle intervals."""

    H1 = "H1"
    H4 = "H4"

    @property
    def seconds(self) -> int:
        return {Timeframe.H1: 3_600, Timeframe.H4: 14_400}[self]


@dataclass(frozen=True)
class Candle:
    """A completed or in-progress MT5 price bar timestamped at its UTC open time."""

    symbol: str
    timeframe: Timeframe
    time_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: int
    spread: int
    real_volume: int

    def __post_init__(self) -> None:
        offset = self.time_utc.utcoffset()
        if self.time_utc.tzinfo is None or offset is None:
            raise ValueError("Candle time must be timezone-aware UTC, not local or naive time.")
        if offset.total_seconds() != 0:
            raise ValueError("Candle time must use UTC; convert it before constructing a Candle.")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("Malformed OHLC: low/open/close/high prices are inconsistent.")
        if self.low > self.high:
            raise ValueError("Malformed OHLC: low is above high.")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("Malformed OHLC: Forex prices must be positive.")
        if min(self.tick_volume, self.spread, self.real_volume) < 0:
            raise ValueError("Candle volume and spread fields cannot be negative.")


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
