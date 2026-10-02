"""Observed broker costs: live spreads sampled every paper cycle and the published swap rates.

The research assumed round-trip costs of 0.9/1.2/1.0 pips (EURUSD/GBPUSD/USDJPY) and no overnight
financing. This records what the broker actually quotes so ``scripts/cost_report.py`` can compare.
It only observes: paper fills and P&L are unchanged. Samples of the hour in progress are lost on
a restart.
"""

from __future__ import annotations

import sqlite3
import statistics
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from forex.domain import SwapRates, Tick, _require_utc


def _hour(now: datetime) -> str:
    return now.replace(minute=0, second=0, microsecond=0).isoformat()


class CostRecorder:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS cost_hours (
                hour_utc TEXT NOT NULL, symbol TEXT NOT NULL, samples INTEGER NOT NULL,
                mean_pips REAL NOT NULL, median_pips REAL NOT NULL, p90_pips REAL NOT NULL,
                max_pips REAL NOT NULL, swap_long REAL, swap_short REAL, swap_mode INTEGER,
                swap_triple_day INTEGER, PRIMARY KEY (hour_utc, symbol))""")
        self.pending: dict[tuple[str, str], list[float]] = {}
        self.broker_names: dict[str, str] = {}

    def observe(self, symbol: str, broker_symbol: str, tick: Tick, pip_size: Decimal, now: datetime) -> None:
        """One spread sample (in pips) for ``symbol`` in the current UTC hour."""
        _require_utc(now, "now")
        self.broker_names[symbol] = broker_symbol
        self.pending.setdefault((_hour(now), symbol), []).append(float((tick.ask - tick.bid) / pip_size))

    def flush(self, now: datetime, swaps: Callable[[str], SwapRates | None]) -> int:
        """Write every finished hour with the current swap rates; the hour in progress keeps collecting."""
        current = _hour(now)
        rows = []
        for key in sorted(k for k in self.pending if k[0] < current):
            values = sorted(self.pending.pop(key))
            swap = swaps(self.broker_names[key[1]])
            rows.append((*key, len(values), statistics.fmean(values), statistics.median(values),
                         values[min(len(values) - 1, int(0.9 * len(values)))], values[-1],
                         *((swap.long, swap.short, swap.mode, swap.triple_day) if swap else (None,) * 4)))
        if rows:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.executemany("INSERT OR REPLACE INTO cost_hours VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)
