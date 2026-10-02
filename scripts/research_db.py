"""Read-only candle access for research scripts (never creates, migrates or locks a database)."""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from forex.domain import Candle, Timeframe


def connect(database: str | Path) -> sqlite3.Connection:
    path = Path(database).resolve()
    if not path.is_file():
        raise SystemExit(f"Research database not found: {path}")
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=60)


def inventory(database: str | Path) -> dict[tuple[str, str], int]:
    """Rows per (symbol, timeframe), to show what a database actually contains."""
    with connect(database) as db:
        rows = db.execute("SELECT symbol, timeframe, COUNT(*) FROM candles GROUP BY symbol, timeframe").fetchall()
    return {(str(s), str(t)): int(n) for s, t, n in rows}


def load_candles(database: str | Path, symbol: str, timeframe: Timeframe) -> list[Candle]:
    with connect(database) as db:
        rows = db.execute("SELECT timestamp_utc, open, high, low, close, tick_volume, spread, real_volume "
                          "FROM candles WHERE symbol=? AND timeframe=? ORDER BY timestamp_utc",
                          (symbol.upper(), timeframe.value)).fetchall()
    return [Candle.from_values(symbol.upper(), timeframe, datetime.fromisoformat(r[0]).astimezone(UTC), *r[1:])
            for r in rows]


def require_data(database: str | Path, symbols: list[str]) -> None:
    """Stop with a clear message if any symbol has no H1/H4 rows."""
    found = inventory(database)
    missing = [f"{s} {t}" for s in symbols for t in ("H1", "H4") if not found.get((s.upper(), t))]
    if missing:
        contents = ", ".join(f"{s} {t}: {n}" for (s, t), n in sorted(found.items())) or "no candles"
        raise SystemExit(f"{database} has no rows for {missing}. It contains: {contents}")
    print(f"{database}: " + ", ".join(f"{s} {t} {n}" for (s, t), n in sorted(found.items())), flush=True)
