"""Broker-neutral market-data validation, storage, and history inspection."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence

from forex.domain import Candle, Timeframe
from forex.errors import OperatorError


class GapKind(str, Enum):
    EXPECTED_WEEKEND = "expected_weekend"
    UNEXPLAINED = "unexplained"


@dataclass(frozen=True)
class CandleGap:
    symbol: str
    timeframe: Timeframe
    previous_open_utc: datetime
    next_open_utc: datetime
    missing_bars: int
    kind: GapKind


@dataclass(frozen=True)
class HistoryDepth:
    symbol: str
    timeframe: Timeframe
    earliest_utc: datetime
    latest_utc: datetime
    candle_count: int

    @property
    def days(self) -> int:
        return (self.latest_utc - self.earliest_utc).days


def validate_candle_order(candles: Sequence[Candle]) -> None:
    """Require strictly increasing, duplicate-free UTC bar-open times."""
    for previous, current in zip(candles, candles[1:]):
        if current.time_utc <= previous.time_utc:
            raise OperatorError(
                f"Candle data for {current.symbol} {current.timeframe.value} is not in strictly "
                "increasing UTC order. Refresh the history from MT5 before continuing."
            )


def is_expected_market_closure(
    start: datetime,
    end: datetime,
    close_hour_utc: int = 22,
    open_hour_utc: int = 22,
) -> bool:
    """Return true only when a gap spans the conventional Friday-to-Sunday FX closure."""
    if end <= start:
        return False
    cursor = start.astimezone(timezone.utc).date() - timedelta(days=2)
    last = end.astimezone(timezone.utc).date()
    while cursor <= last:
        if cursor.weekday() == 4:  # UNVALIDATED — broker/DST hours are configurable.
            close = datetime.combine(cursor, datetime.min.time(), timezone.utc).replace(
                hour=close_hour_utc
            )
            reopen = close + timedelta(days=2)
            reopen = reopen.replace(hour=open_hour_utc)
            if close - timedelta(hours=4) <= start <= close and close <= end <= reopen + timedelta(
                hours=4
            ):
                return True
        cursor += timedelta(days=1)
    return False


def detect_gaps(
    candles: Sequence[Candle],
    close_hour_utc: int = 22,
    open_hour_utc: int = 22,
) -> list[CandleGap]:
    """Classify absent intervals without turning the normal Sunday reopen into a signal."""
    validate_candle_order(candles)
    gaps: list[CandleGap] = []
    for previous, current in zip(candles, candles[1:]):
        difference = int((current.time_utc - previous.time_utc).total_seconds())
        missing = difference // previous.timeframe.seconds - 1
        if missing <= 0:
            continue
        expected = is_expected_market_closure(
            previous.time_utc, current.time_utc, close_hour_utc, open_hour_utc
        )
        gaps.append(
            CandleGap(
                previous.symbol,
                previous.timeframe,
                previous.time_utc,
                current.time_utc,
                missing,
                GapKind.EXPECTED_WEEKEND if expected else GapKind.UNEXPLAINED,
            )
        )
    return gaps


def assert_fresh(
    timestamp: datetime,
    now: datetime,
    maximum_age: timedelta,
    label: str,
    close_hour_utc: int = 22,
    open_hour_utc: int = 22,
) -> None:
    """Fail loudly when data is old outside a configured market closure."""
    if timestamp.tzinfo is None or now.tzinfo is None:
        raise ValueError("Freshness checks require timezone-aware UTC datetimes.")
    age = now - timestamp
    if age <= maximum_age:
        return
    if is_expected_market_closure(timestamp, now, close_hour_utc, open_hour_utc):
        return
    raise OperatorError(
        f"Stale market data: {label} is {age} old, exceeding the configured limit of "
        f"{maximum_age}. Do not trade. Check the MT5 connection and Market Watch price updates, "
        "then rerun Layer 2 verification."
    )


class CandleRepository:
    """Transactionally persist and reload normalized candles from local SQLite."""

    def __init__(self, path: Path):
        self.path = path

    def upsert(self, candles: Iterable[Candle]) -> int:
        rows = [
            (
                candle.symbol,
                candle.timeframe.value,
                candle.time_utc.astimezone(timezone.utc).isoformat(),
                str(candle.open),
                str(candle.high),
                str(candle.low),
                str(candle.close),
                candle.tick_volume,
                candle.spread,
                candle.real_volume,
            )
            for candle in candles
        ]
        if not rows:
            return 0
        with sqlite3.connect(self.path) as connection:
            connection.executemany(
                """
                INSERT INTO candles (
                    symbol, timeframe, time_utc, open, high, low, close,
                    tick_volume, spread, real_volume
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe, time_utc) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                    tick_volume=excluded.tick_volume, spread=excluded.spread,
                    real_volume=excluded.real_volume
                """,
                rows,
            )
        return len(rows)

    def load(self, symbol: str, timeframe: Timeframe) -> list[Candle]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """SELECT time_utc, open, high, low, close, tick_volume, spread, real_volume
                   FROM candles WHERE symbol=? AND timeframe=? ORDER BY time_utc ASC""",
                (symbol, timeframe.value),
            ).fetchall()
        return [
            Candle(
                symbol,
                timeframe,
                datetime.fromisoformat(row[0]).astimezone(timezone.utc),
                Decimal(row[1]),
                Decimal(row[2]),
                Decimal(row[3]),
                Decimal(row[4]),
                int(row[5]),
                int(row[6]),
                int(row[7]),
            )
            for row in rows
        ]

    def depth(self, symbol: str, timeframe: Timeframe) -> HistoryDepth | None:
        candles = self.load(symbol, timeframe)
        if not candles:
            return None
        return HistoryDepth(symbol, timeframe, candles[0].time_utc, candles[-1].time_utc, len(candles))
