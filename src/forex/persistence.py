"""Transactional local persistence foundation."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from forex.domain import Candle, Timeframe
from forex.risk import DailyRiskState

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
CREATE TABLE IF NOT EXISTS risk_sessions (
    session_id TEXT PRIMARY KEY, opening_balance TEXT NOT NULL,
    circuit_breaker_triggered INTEGER NOT NULL CHECK(circuit_breaker_triggered IN (0, 1)),
    triggered_at_utc TEXT, kill_switch_active INTEGER NOT NULL CHECK(kill_switch_active IN (0, 1)),
    updated_at_utc TEXT NOT NULL
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


class RiskSessionStore:
    """Transactional persistence for latches only; never an open-position authority."""

    def __init__(self, path: Path):
        self.path = path
        initialise_database(path)

    def save(self, state: DailyRiskState, updated_at_utc: datetime,
             triggered_at_utc: datetime | None = None) -> None:
        for value, name in ((updated_at_utc, "updated_at_utc"),
                            (triggered_at_utc, "triggered_at_utc")):
            if value is not None and (value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)):
                raise ValueError(f"{name} must be timezone-aware UTC")
        with sqlite3.connect(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """INSERT INTO risk_sessions VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                opening_balance=excluded.opening_balance,
                circuit_breaker_triggered=MAX(risk_sessions.circuit_breaker_triggered,
                                               excluded.circuit_breaker_triggered),
                triggered_at_utc=COALESCE(risk_sessions.triggered_at_utc,
                                           excluded.triggered_at_utc),
                kill_switch_active=excluded.kill_switch_active,
                updated_at_utc=excluded.updated_at_utc""",
                (state.session_id, str(state.opening_balance), state.circuit_breaker_triggered,
                 triggered_at_utc.isoformat() if triggered_at_utc else None,
                 state.kill_switch_active, updated_at_utc.isoformat()),
            )

    def load(self, session_id: str, current_equity: Decimal) -> DailyRiskState | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """SELECT opening_balance, circuit_breaker_triggered, kill_switch_active
                FROM risk_sessions WHERE session_id=?""", (session_id,)).fetchone()
        if row is None:
            return None
        return DailyRiskState(session_id, Decimal(row[0]), current_equity, bool(row[1]), bool(row[2]))
