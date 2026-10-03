"""Coverage check of research candle databases (read-only).

Usage:
  python scripts/data_coverage.py data/rebuilt/dukascopy-2012-2018.sqlite3 data/rebuilt/dukascopy-research.sqlite3

For every pair in each database, this reports:
- first and last H1 candle;
- how many weekday trading hours are missing (weekends excluded with the same rule as
  `forex verify-history`);
- every gap of at least --report-hours missing trading hours;
- calendar months with less than --month-threshold of their expected hours.

Gaps of at least 48 trading hours split the history into segments in scripts/causal_replay.py:
indicators restart after them and no trade may span one. Run this before trusting any result
from a database, and re-download the missing ranges if material gaps exist.
"""
from __future__ import annotations

import argparse
import itertools
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from research_db import connect, missing_trading_hours

from forex.config import MarketDataConfig
from forex.market_data import _in_weekend


def h1_times(database: str, symbol: str) -> list[datetime]:
    with connect(database) as db:
        rows = db.execute("SELECT timestamp_utc FROM candles WHERE symbol=? AND timeframe='H1' "
                          "ORDER BY timestamp_utc", (symbol,)).fetchall()
    return [datetime.fromisoformat(r[0]).astimezone(UTC) for r in rows]


def gaps(times: list[datetime]) -> list[tuple[datetime, datetime, int]]:
    """(last bar before, first bar after, missing weekday trading hours) for every hole."""
    found = []
    for before, after in itertools.pairwise(times):
        if after - before > timedelta(hours=1):
            missing = missing_trading_hours(before, after)
            if missing:
                found.append((before, after, missing))
    return found


def h4_alignment(database: str) -> list[str]:
    """The H4 boundary rule recorded when the database was imported (e.g. 'fixed UTC boundary hour 0')."""
    with connect(database) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='history_imports'").fetchone():
            return ["not recorded"]
        return sorted({str(r[0]) for r in db.execute("SELECT h4_alignment FROM history_imports").fetchall()})


def month_coverage(times: list[datetime], config: MarketDataConfig) -> dict[str, tuple[int, int]]:
    """(present, expected) trading hours per calendar month between the first and last bar."""
    present: dict[str, int] = defaultdict(int)
    for t in times:
        present[t.strftime("%Y-%m")] += 1
    expected: dict[str, int] = defaultdict(int)
    cursor = times[0]
    while cursor <= times[-1]:
        if not _in_weekend(cursor, config):
            expected[cursor.strftime("%Y-%m")] += 1
        cursor += timedelta(hours=1)
    return {m: (present.get(m, 0), n) for m, n in sorted(expected.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("databases", nargs="+")
    parser.add_argument("--symbols", default="EURUSD,GBPUSD,USDJPY")
    parser.add_argument("--report-hours", type=int, default=24)
    parser.add_argument("--month-threshold", type=float, default=0.9)
    parser.add_argument("--json", action="store_true", help="Print machine-readable output only")
    args = parser.parse_args()
    config = MarketDataConfig()
    result: dict[str, dict[str, object]] = {}
    for database in args.databases:
        result[f"{database}|H4"] = {"h4_alignment": h4_alignment(database)}
        for symbol in (s.strip().upper() for s in args.symbols.split(",")):
            times = h1_times(database, symbol)
            key = f"{database}|{symbol}"
            if not times:
                result[key] = {"rows": 0}
                continue
            holes = gaps(times)
            months = month_coverage(times, config)
            thin = {m: f"{p}/{n}" for m, (p, n) in months.items() if p < args.month_threshold * n}
            result[key] = {
                "first": times[0].isoformat(), "last": times[-1].isoformat(), "rows": len(times),
                "missing_trading_hours": sum(h for _, _, h in holes),
                "gaps_at_least_report_hours": [
                    {"after": a.isoformat(), "resumes": b.isoformat(), "missing_hours": h}
                    for a, b, h in holes if h >= args.report_hours],
                "segment_breaks_48h": sum(h >= 48 for _, _, h in holes),
                "thin_months": thin,
            }
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    for key, info in result.items():
        print(f"\n{key}")
        if "h4_alignment" in info:
            print(f"  H4 bars built with: {', '.join(info['h4_alignment'])}")  # type: ignore[arg-type]
            continue
        if not info.get("rows"):
            print("  no H1 rows")
            continue
        print(f"  {info['first'][:16]} to {info['last'][:16]}, {info['rows']} H1 rows, "
              f"{info['missing_trading_hours']} weekday trading hours missing, "
              f"{info['segment_breaks_48h']} gaps of 48+ hours")
        for g in info["gaps_at_least_report_hours"]:  # type: ignore[union-attr]
            print(f"  GAP {g['after'][:16]} -> {g['resumes'][:16]}  ({g['missing_hours']} trading hours)")
        for month, share in info["thin_months"].items():  # type: ignore[union-attr]
            print(f"  THIN MONTH {month}: {share} trading hours present")
    print("\nRead: no GAP / THIN MONTH lines means the history is complete enough to trust.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
