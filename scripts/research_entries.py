"""Research only: test entry-timing and stop-size variants on exported OOS trades.

Uses reports/backtest/oos-trades.csv from research_trades.py. "Signal N in a row" means the same
pair/direction/setup produced a signal on N consecutive closed hours; entering only from the Nth
one is a confirmation rule. Costs are the same ASSUMED values as research_summary.py.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from research_summary import DEFAULT_COST_PIPS, LIVE_BANDS, Row, load, one_at_a_time, stats


def number_signals(rows: list[Row]) -> None:
    """Annotate each trend signal with its position in a run of consecutive hourly signals."""
    last: dict[tuple[str, str, str], tuple[object, int]] = {}
    for t in rows:
        key = (str(t["symbol"]), str(t["side"]), str(t["setup"]))
        previous = last.get(key)
        position = previous[1] + 1 if previous and t["signal"] - previous[0] <= timedelta(hours=1) else 1  # type: ignore[operator]
        t["position"] = position
        last[key] = (t["signal"], position)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=Path("reports/backtest/oos-trades.csv"))
    args = parser.parse_args()
    rows = load(args.file, DEFAULT_COST_PIPS, 1.0)
    number_signals(rows)
    span = (max(t["signal"] for t in rows) - min(t["signal"] for t in rows)).days / 7  # type: ignore[operator]
    trend = [t for t in rows if str(t["setup"]).startswith("TREND")]
    print(f"Trend signals: {len(trend)} over {span:.0f} weeks. Costs assumed: {DEFAULT_COST_PIPS} pips.")
    print("\nAverage result by position in a run of consecutive hourly trend signals (every signal, NET):")
    by_position: dict[int, list[float]] = defaultdict(list)
    for t in trend:
        by_position[min(int(t["position"]), 6)].append(float(t["net"]))  # type: ignore[arg-type]
    for position, values in sorted(by_position.items()):
        label = f"{position}{'+' if position == 6 else ''}"
        print(f"  signal {label:<3} in a row: {len(values):>6} trades  avg {sum(values) / len(values):+.3f} R")
    variants = []
    for live in (False, True):
        base = [t for t in trend if not live or t["band"] in LIVE_BANDS]
        tag = "trend, conf>=55" if live else "trend, any conf"
        variants.append((f"{tag}: first signal (current behaviour)", base))
        for n in (2, 3, 4):
            variants.append((f"{tag}: enter from signal {n} in a row", [t for t in base if int(t["position"]) >= n]))  # type: ignore[arg-type]
        for pips in (10, 15, 25):
            variants.append((f"{tag}: skip stops under {pips} pips", [t for t in base if float(t["stop_pips"]) >= pips]))  # type: ignore[arg-type]
    print("\nOne trade at a time per pair, NET of assumed costs:")
    for name, selected in variants:
        print(f"  {name:<50} {stats(one_at_a_time(selected), 'net', span)}")
    print("\nPer pair, trend + conf>=55, one at a time, NET:")
    for symbol in sorted({str(t["symbol"]) for t in trend}):
        selected = [t for t in trend if t["symbol"] == symbol and t["band"] in LIVE_BANDS]
        print(f"  {symbol}: {stats(one_at_a_time(selected), 'net', span)}")
    print("\nSampling noise: with ~300 trades, +/-0.07 R per trade is within chance. Research only.")


if __name__ == "__main__":
    main()
