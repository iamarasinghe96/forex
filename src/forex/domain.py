"""Stable broker-neutral types shared by live code and test doubles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum


class AccountMode(str, Enum):
    HEDGING = "hedging"
    NETTING = "netting"


class Timeframe(str, Enum):
    H1 = "H1"
    H4 = "H4"

    @property
    def duration(self) -> timedelta:
        return timedelta(hours=1 if self is Timeframe.H1 else 4)


def _require_utc(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field} must use UTC")


def _integer(value: object, field: str) -> int:
    converted = Decimal(str(value))
    if converted != converted.to_integral_value():
        raise ValueError(f"{field} must be an integer")
    return int(converted)


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: Timeframe
    timestamp_utc: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: int
    spread: int
    real_volume: int

    def __post_init__(self) -> None:
        _require_utc(self.timestamp_utc, "timestamp_utc")
        if not self.symbol:
            raise ValueError("symbol must not be empty")
        prices = (self.open, self.high, self.low, self.close)
        if any(not price.is_finite() or price <= 0 for price in prices):
            raise ValueError("OHLC prices must be finite and positive")
        if self.high < max(prices) or self.low > min(prices):
            raise ValueError("candle high/low does not contain its OHLC prices")
        if any(value < 0 for value in (self.tick_volume, self.spread, self.real_volume)):
            raise ValueError("candle volume and spread fields must be non-negative")

    @classmethod
    def from_values(
        cls, symbol: str, timeframe: Timeframe, timestamp: datetime, open_: object,
        high: object, low: object, close: object, tick_volume: object, spread: object,
        real_volume: object,
    ) -> Candle:
        """Normalize a source timestamp to UTC and validate all source fields."""
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("source candle timestamp must be timezone-aware")
        return cls(symbol, timeframe, timestamp.astimezone(UTC), Decimal(str(open_)),
                   Decimal(str(high)), Decimal(str(low)), Decimal(str(close)),
                   _integer(tick_volume, "tick_volume"), _integer(spread, "spread"),
                   _integer(real_volume, "real_volume"))


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
class SwapRates:
    """Overnight financing as the broker publishes it (MT5 symbol properties, raw units)."""

    symbol: str
    long: float
    short: float
    mode: int          # MT5 SYMBOL_SWAP_MODE_*; 1 = points per lot per night.
    triple_day: int    # Day of week charged three nights (0 = Sunday ... 6 = Saturday).


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
