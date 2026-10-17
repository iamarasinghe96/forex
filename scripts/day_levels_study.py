"""Research only: the previous-day high/low study (forex.day_levels) on a candle database.

The bot's /levels command runs the same study on the prices it has stored (about a year). This runs
it on a longer history, e.g. the 2012-2026 research databases, and prints the full report:

    python scripts/day_levels_study.py --database data/dukascopy-research.sqlite3
    python scripts/day_levels_study.py --database data/dukascopy-2012-2018.sqlite3 --start 2012-01-01

The database is opened read-only.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from research_db import load_candles

from forex.day_levels import levels_report
from forex.domain import Timeframe


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=Path("data/dukascopy-research.sqlite3"))
    parser.add_argument("--symbols", nargs="+", default=["EURUSD", "GBPUSD", "USDJPY"])
    parser.add_argument("--start", help="First date (YYYY-MM-DD), optional")
    parser.add_argument("--end", help="Last date, exclusive (YYYY-MM-DD), optional")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC) if args.start else None
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC) if args.end else None
    by_symbol = {}
    for symbol in args.symbols:
        bars = load_candles(args.database, symbol, Timeframe.H1)
        by_symbol[symbol] = [b for b in bars if (start is None or b.timestamp_utc >= start)
                             and (end is None or b.timestamp_utc < end)]
    print(levels_report(by_symbol)[1])


if __name__ == "__main__":
    main()
