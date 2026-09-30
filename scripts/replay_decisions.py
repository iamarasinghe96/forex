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


COST_PIPS = {"EURUSD": 0.9, "GBPUSD": 1.2, "USDJPY": 1.0}  # Same assumptions as the research scripts.


class Position:
    """Rough live-rule simulation: structural stop, 1.5R target, stop to entry at +1R."""

    def __init__(self, side: str, entry: float, stop: float, reward_risk: float, opened: datetime):
        self.side, self.entry, self.stop, self.opened = side, entry, stop, opened
        self.sign = 1 if side == "LONG" else -1
        self.risk = abs(entry - stop)
        self.target = entry + self.sign * reward_risk * self.risk
        self.breakeven = False

    def manage(self, candle: Candle) -> tuple[float, str] | None:
        high, low = float(candle.high), float(candle.low)
        adverse, favourable = (low, high) if self.sign > 0 else (high, low)
        if (adverse - self.stop) * self.sign <= 0:  # Stop first when both touch (adverse).
            return self.stop, "breakeven" if self.breakeven else "stop"
        if (favourable - self.target) * self.sign >= 0:
            return self.target, "target"
        if not self.breakeven and (favourable - self.entry) * self.sign >= self.risk:
            self.stop, self.breakeven = self.entry, True
        return None


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
        trades: list[str] = []
        net_r = net_pips = 0.0
        position: Position | None = None
        cost = COST_PIPS.get(symbol.upper(), 1.0) * pip(symbol)
        for candle in h1:
            now = candle.timestamp_utc + timedelta(hours=1)
            if not since <= candle.timestamp_utc < until:
                continue
            day = candle.timestamp_utc.date().isoformat()
            first_last = moves.setdefault(day, [float(candle.open), float(candle.close)])
            first_last[1] = float(candle.close)
            if position is not None:
                closed = position.manage(candle)
                if closed is not None:
                    price, why = closed
                    move = (price - position.entry) * position.sign - cost
                    net_r += move / position.risk
                    net_pips += move / pip(symbol)
                    trades.append(f"  {position.opened:%m-%d %H:%M} {position.side:5s} -> "
                                  f"{now:%m-%d %H:%M} {why:9s} {move / pip(symbol):+6.0f} pips "
                                  f"{move / position.risk:+5.2f} R")
                    position = None
            result = analyse_market(symbol, p1.closed(now), p4.closed(now), now, config.analysis)
            snap = result.snapshot
            if position is None and result.candidate is not None:
                side = result.candidate.side.value
                levels = result.candidate.structural_reference_levels
                stop = float(levels["rolling_low" if side == "LONG" else "rolling_high"])
                entry = float(candle.close)
                if (entry - stop) * (1 if side == "LONG" else -1) > 0:
                    position = Position(side, entry, stop, float(config.backtest.reward_risk), now)
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
        print(f"  Simulated trades (one at a time, after {cost / pip(symbol):.1f} pip cost):")
        print("\n".join(trades) if trades else "  none")
        if position is not None:
            print(f"  {position.opened:%m-%d %H:%M} {position.side:5s} -> still open")
        print(f"  Closed total: {net_pips:+.0f} pips, {net_r:+.2f} R")
    print("\nCANDIDATE = hours with a trade idea. Simulated trades are rough: entry at the hour's close,"
          "\nstructural stop, 1.5R target, stop to entry at +1R; the live bot's risk checks and news"
          "\nreview are not applied. A few weeks is an anecdote, not evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
