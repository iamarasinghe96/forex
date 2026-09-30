"""Replay the bot's hourly analysis over stored candles and explain each day (read-only).

Usage: python scripts/replay_decisions.py --since 2026-09-09 [--until 2026-10-01]
       [--db data/paper.sqlite3] [--config config.yaml]

Uses the installed strategy code and config.yaml on the H1/H4 candles the paper bot already
saved, so it shows what the bot would have decided on days it was not running. Opens the
database read-only; places no orders and changes nothing.
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from forex.analysis import analyse_market, prepare_candles
from forex.config import load_config
from forex.domain import Candle, Timeframe


def load(db: sqlite3.Connection, stored_symbol: str, symbol: str, timeframe: Timeframe) -> list[Candle]:
    rows = db.execute(
        "SELECT timestamp_utc, open, high, low, close, tick_volume, spread, real_volume FROM candles "
        "WHERE symbol=? AND timeframe=? ORDER BY timestamp_utc", (stored_symbol, timeframe.value)).fetchall()
    return [Candle.from_values(symbol, timeframe, datetime.fromisoformat(r[0]).astimezone(UTC), *r[1:])
            for r in rows]


def pip(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path("data/paper.sqlite3"))
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--since", required=True, help="UTC date, e.g. 2026-09-09")
    parser.add_argument("--until", default=None, help="UTC date (exclusive); default now")
    args = parser.parse_args()
    config = load_config(args.config)
    since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
    until = datetime.fromisoformat(args.until).replace(tzinfo=UTC) if args.until else datetime.now(UTC)
    db = sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True)
    stored = [row[0] for row in db.execute("SELECT DISTINCT symbol FROM candles")]
    threshold = config.analysis.trend_threshold
    for symbol in config.broker.symbols:
        match = next((s for s in stored if s.upper().split(".")[0] == symbol.upper()), None)
        if match is None:
            print(f"\n=== {symbol}: no stored candles ===")
            continue
        h1 = load(db, match, symbol, Timeframe.H1)
        h4 = load(db, match, symbol, Timeframe.H4)
        p1, p4 = prepare_candles(h1, config.analysis), prepare_candles(h4, config.analysis)
        days: dict[str, Counter[str]] = defaultdict(Counter)
        moves: dict[str, list[float]] = {}
        reasons: Counter[str] = Counter()
        for candle in h1:
            now = candle.timestamp_utc + timedelta(hours=1)
            if not since <= candle.timestamp_utc < until:
                continue
            day = candle.timestamp_utc.date().isoformat()
            first_last = moves.setdefault(day, [float(candle.open), float(candle.close)])
            first_last[1] = float(candle.close)
            snap = analyse_market(symbol, p1.closed(now), p4.closed(now), now, config.analysis).snapshot
            label = snap.regime.label.value
            if snap.candidate_generated:
                days[day]["CANDIDATE"] += 1
            elif label == "HIGH_VOLATILITY" and snap.regime.trend_strength >= threshold:
                side = "down" if snap.regime.directional_bias < 0 else "up"
                days[day][f"HIGH_VOL(trend {side})"] += 1
                reasons["HIGH_VOLATILITY while the trend measure was strong"] += 1
            else:
                days[day][label] += 1
                reasons[str(snap.no_candidate_reason)] += 1
        total = sum(sum(c.values()) for c in days.values())
        candidates = sum(c["CANDIDATE"] for c in days.values())
        print(f"\n=== {symbol}: {total} hours replayed, {candidates} trade ideas ===")
        for reason, n in reasons.most_common():
            print(f"  {n:5d}  {reason}")
        print("  Day         move(pips)  hours by label")
        for day in sorted(days):
            first, last = moves[day]
            move = (last - first) / pip(symbol)
            print(f"  {day}  {move:+9.0f}   " + ", ".join(f"{k} {n}" for k, n in days[day].most_common()))
    print("\nCANDIDATE = hours with a trade idea; the live bot holds one position per pair, so many"
          "\nidea-hours can mean a single trade, and risk checks and news review still apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
