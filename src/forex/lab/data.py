"""Historical hourly prices for the strategy lab, read-only, split at data holes."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from forex.config import MarketDataConfig
from forex.day_levels import rolling_atr
from forex.domain import Candle, Timeframe
from forex.market_data import _in_weekend

MAX_GAP_HOURS = 48  # This many missing weekday hours splits the data, as in the earlier research.


def read_candles(database: Path, symbol: str) -> list[Candle]:
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=60)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='candles'").fetchone():
            return []
        rows = db.execute("SELECT timestamp_utc, open, high, low, close, tick_volume, spread, real_volume "
                          "FROM candles WHERE symbol=? AND timeframe=? ORDER BY timestamp_utc",
                          (symbol.upper(), Timeframe.H1.value)).fetchall()
    return [Candle.from_values(symbol.upper(), Timeframe.H1, datetime.fromisoformat(r[0]).astimezone(UTC), *r[1:])
            for r in rows]


def missing_trading_hours(before: datetime, after: datetime) -> int:
    config = MarketDataConfig()
    hours = int((after - before) / timedelta(hours=1)) - 1
    return sum(not _in_weekend(before + timedelta(hours=k), config) for k in range(1, hours + 1))


@dataclass
class Series:
    """One pair's hourly bars as plain numbers, with ATR at each close and data-hole segments."""

    symbol: str
    bars: list[Candle]
    times: list[datetime]
    o: list[float]
    h: list[float]
    l: list[float]
    c: list[float]
    atr: list[float | None]
    segment: list[int]
    index: dict[datetime, int]

    def segment_ranges(self) -> list[tuple[int, int]]:
        ranges, start = [], 0
        for i in range(1, len(self.bars) + 1):
            if i == len(self.bars) or self.segment[i] != self.segment[start]:
                ranges.append((start, i))
                start = i
        return ranges

    def fingerprint(self) -> str:
        digest = hashlib.sha256(f"{self.symbol}|{len(self.bars)}|{self.times[0]}|{self.times[-1]}".encode())
        for i in range(0, len(self.c), 97):
            digest.update(f"{self.c[i]:.6f}".encode())
        return digest.hexdigest()[:16]


def build_series(symbol: str, candles: Sequence[Candle]) -> Series:
    bars = sorted({b.timestamp_utc: b for b in candles}.values(), key=lambda b: b.timestamp_utc)
    segment, number = [], 0
    for i, bar in enumerate(bars):
        if i and (bar.timestamp_utc - bars[i - 1].timestamp_utc > timedelta(hours=MAX_GAP_HOURS)
                  and missing_trading_hours(bars[i - 1].timestamp_utc, bar.timestamp_utc) >= MAX_GAP_HOURS):
            number += 1
        segment.append(number)
    series = Series(symbol.upper(), bars, [b.timestamp_utc for b in bars], [float(b.open) for b in bars],
                    [float(b.high) for b in bars], [float(b.low) for b in bars], [float(b.close) for b in bars],
                    [None] * len(bars), segment, {b.timestamp_utc: i for i, b in enumerate(bars)})
    for start, end in series.segment_ranges():  # ATR restarts after a hole.
        for when, value in rolling_atr(bars[start:end]).items():
            series.atr[series.index[when]] = value
    return series


@dataclass
class History:
    series: dict[str, Series]
    sources: list[Path]
    fallback: bool

    def describe(self) -> str:
        lines = [f"Data: {', '.join(str(p) for p in self.sources)}"
                 + (" (fallback: the research databases were not found)" if self.fallback else "")]
        for s in self.series.values():
            holes = s.segment[-1] if s.segment else 0
            lines.append(f"  {s.symbol}: {len(s.bars):,} hours, {s.times[0]:%Y-%m-%d} to {s.times[-1]:%Y-%m-%d}"
                         + (f", {holes} data hole(s) of {MAX_GAP_HOURS}+ hours" if holes else ""))
        return "\n".join(lines)


def load_history(databases: Sequence[Path], fallback: Sequence[Path], pairs: Sequence[str]) -> History:
    """Every listed database that exists, later files winning on overlapping hours."""
    found, used_fallback = [p for p in databases if p.is_file()], False
    if not found:
        found, used_fallback = [p for p in fallback if p.is_file()], True
    if not found:
        listed = ", ".join(str(p) for p in [*databases, *fallback])
        raise SystemExit(f"No price database found. Looked for: {listed}. Edit data.databases in strategy-lab.yaml.")
    series = {}
    for pair in pairs:
        merged: dict[datetime, Candle] = {}
        for path in found:
            merged.update({c.timestamp_utc: c for c in read_candles(path, pair)})
        if merged:
            series[pair.upper()] = build_series(pair, list(merged.values()))
    if not series:
        raise SystemExit(f"The databases {', '.join(map(str, found))} hold no H1 prices for {', '.join(pairs)}. "
                         "Download the history once with tools\\get-history.bat.")
    return History(series, found, used_fallback)
