"""Transactional local persistence foundation."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from forex.domain import Candle, Timeframe

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL, payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL, synced_at_utc TEXT
);
INSERT OR IGNORE INTO schema_version(version, applied_at_utc)
VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL, timeframe TEXT NOT NULL, timestamp_utc TEXT NOT NULL,
    open TEXT NOT NULL, high TEXT NOT NULL, low TEXT NOT NULL, close TEXT NOT NULL,
    tick_volume INTEGER NOT NULL, spread INTEGER NOT NULL, real_volume INTEGER NOT NULL,
    PRIMARY KEY(symbol, timeframe, timestamp_utc)
);
"""


def initialise_database(path: Path) -> None:
    """Create the local database atomically and enable crash-resistant WAL journaling."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(SCHEMA)


class CandleStore:
    """Transactional, idempotent storage for broker-neutral candles."""

    def __init__(self, path: Path):
        self.path = path
        initialise_database(path)

    def upsert(self, candles: Sequence[Candle]) -> None:
        values = [
            (c.symbol, c.timeframe.value, c.timestamp_utc.isoformat(), str(c.open), str(c.high),
             str(c.low), str(c.close), c.tick_volume, c.spread, c.real_volume)
            for c in candles
        ]
        with sqlite3.connect(self.path) as connection:
            connection.executemany(
                """INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timeframe,timestamp_utc) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                tick_volume=excluded.tick_volume, spread=excluded.spread,
                real_volume=excluded.real_volume""", values,
            )

    def load(self, symbol: str, timeframe: Timeframe) -> list[Candle]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """SELECT timestamp_utc, open, high, low, close, tick_volume, spread, real_volume
                FROM candles WHERE symbol=? AND timeframe=? ORDER BY timestamp_utc ASC""",
                (symbol.upper(), timeframe.value),
            ).fetchall()
        return [
            Candle.from_values(symbol.upper(), timeframe, datetime.fromisoformat(row[0]).astimezone(UTC),
                               *row[1:])
            for row in rows
        ]
