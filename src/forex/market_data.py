"""Read-only market-data validation, gap analysis, and bounded history download."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from forex.broker.mt5 import MT5Broker
from forex.config import MarketDataConfig
from forex.domain import Candle, Tick, Timeframe
from forex.errors import OperatorError
from forex.persistence import CandleStore


@dataclass(frozen=True)
class Gap:
    previous_utc: datetime
    next_utc: datetime
    missing_bars: int


@dataclass(frozen=True)
class GapReport:
    expected_weekend_gaps: int
    expected_weekend_missing_bars: int
    unexplained_gaps: tuple[Gap, ...]

    @property
    def unexplained_missing_bars(self) -> int:
        return sum(gap.missing_bars for gap in self.unexplained_gaps)


@dataclass(frozen=True)
class HistoryReport:
    symbol: str
    timeframe: Timeframe
    earliest_utc: datetime
    latest_utc: datetime
    candle_count: int
    depth_days: float
    approximate_years: float
    gaps: GapReport


def _in_weekend(value: datetime, config: MarketDataConfig) -> bool:
    minute = value.weekday() * 1440 + value.hour * 60 + value.minute
    close = config.weekend_close_weekday * 1440 + config.weekend_close_hour_utc * 60
    opening = config.weekend_open_weekday * 1440 + config.weekend_open_hour_utc * 60
    if close <= opening:
        return close <= minute < opening
    return minute >= close or minute < opening


def detect_gaps(candles: list[Candle], config: MarketDataConfig) -> GapReport:
    if len(candles) < 2:
        return GapReport(0, 0, ())
    ordered = sorted({c.timestamp_utc: c for c in candles}.values(), key=lambda c: c.timestamp_utc)
    expected_events = expected_bars = 0
    unexplained: list[Gap] = []
    for previous, following in pairwise(ordered):
        duration = previous.timeframe.duration
        missing = int((following.timestamp_utc - previous.timestamp_utc) / duration) - 1
        if missing <= 0:
            continue
        absent = [previous.timestamp_utc + duration * step for step in range(1, missing + 1)]
        weekend_count = sum(_in_weekend(value, config) for value in absent)
        if weekend_count:
            expected_events += 1
            expected_bars += weekend_count
        unexplained_count = missing - weekend_count
        if unexplained_count:
            unexplained.append(Gap(previous.timestamp_utc, following.timestamp_utc,
                                   unexplained_count))
    return GapReport(expected_events, expected_bars, tuple(unexplained))


def _open_market_elapsed(start: datetime, end: datetime, config: MarketDataConfig) -> timedelta:
    cursor = start
    elapsed = timedelta()
    step = timedelta(minutes=30)
    while cursor < end:
        next_cursor = min(cursor + step, end)
        if not _in_weekend(cursor, config):
            elapsed += next_cursor - cursor
        cursor = next_cursor
    return elapsed


def validate_freshness(
    timestamp: datetime, now: datetime, threshold: timedelta, config: MarketDataConfig,
    description: str,
) -> None:
    if timestamp.tzinfo is None or now.tzinfo is None:
        raise ValueError("freshness timestamps must be timezone-aware")
    timestamp, now = timestamp.astimezone(UTC), now.astimezone(UTC)
    if timestamp > now:
        raise OperatorError(f"{description} timestamp is in the future; check the VPS clock.")
    age = _open_market_elapsed(timestamp, now, config)
    if age > threshold:
        raise OperatorError(
            f"{description} is stale: last update {timestamp.isoformat()}, open-market age {age}. "
            "Check MT5 is connected, Market Watch is updating, and the VPS clock is correct."
        )


def validate_tick_freshness(tick: Tick, now: datetime, config: MarketDataConfig) -> None:
    validate_freshness(tick.time_utc, now, timedelta(hours=config.stale_h1_hours), config,
                       f"Tick for {tick.symbol}")


def validate_candle_freshness(candle: Candle, now: datetime, config: MarketDataConfig) -> None:
    hours = config.stale_h1_hours if candle.timeframe is Timeframe.H1 else config.stale_h4_hours
    validate_freshness(candle.timestamp_utc, now, timedelta(hours=hours), config,
                       f"{candle.timeframe.value} candle for {candle.symbol}")


def download_history(
    broker: MT5Broker, store: CandleStore, symbol: str, timeframe: Timeframe,
    config: MarketDataConfig, end: datetime | None = None,
) -> HistoryReport:
    cursor = (end or datetime.now(UTC)).astimezone(UTC)
    chunk = timedelta(days=config.history_chunk_days)
    found = False
    while True:
        start = cursor - chunk
        candles = broker._candles(symbol, timeframe, start, cursor, allow_empty=True,
                                  retries=config.history_retry_count)
        if not candles:
            if not found:
                raise OperatorError(
                    f"MT5 exposes no {timeframe.value} history for {symbol}. Open its chart, "
                    "increase Tools > Options > Charts > Max bars in chart, load history, and retry."
                )
            break
        found = True
        store.upsert(candles)
        earliest = candles[0].timestamp_utc
        if earliest <= start + timeframe.duration:
            cursor = start
        else:
            # A partial oldest chunk is MT5's currently exposed boundary.
            break
    saved = store.load(symbol, timeframe)
    earliest, latest = saved[0].timestamp_utc, saved[-1].timestamp_utc
    days = (latest - earliest).total_seconds() / 86400
    return HistoryReport(symbol.upper(), timeframe, earliest, latest, len(saved), days,
                         days / 365.2425, detect_gaps(saved, config))
