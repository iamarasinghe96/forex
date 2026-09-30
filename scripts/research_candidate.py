"""Research only: evaluate the PRE-REGISTERED candidate on an exported trade file.

Candidate (registered 2026-09-30 before any 2012-2018 data was examined):
  trend setups only, confidence >= 55, enter only from the 3rd consecutive hourly signal,
  one open trade per pair, all three pairs, assumed round-trip costs from research_summary.py.
Pass: net average R > 0 AND net profit factor > 1 across all pairs combined.
Per-pair and per-year results are reported for information and do not change the verdict.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from research_entries import number_signals
from research_summary import DEFAULT_COST_PIPS, LIVE_BANDS, Row, load, one_at_a_time, stats


def candidate(rows: list[Row]) -> list[Row]:
    return one_at_a_time([t for t in rows if str(t["setup"]).startswith("TREND")
                          and t["band"] in LIVE_BANDS and int(t["position"]) >= 3])  # type: ignore[arg-type]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    rows = load(args.file, DEFAULT_COST_PIPS, 1.0)
    number_signals(rows)
    span = (max(t["signal"] for t in rows) - min(t["signal"] for t in rows)).days / 7  # type: ignore[operator]
    taken = candidate(rows)
    print(f"{len(rows)} exported trades, {span:.0f} weeks, {min(t['signal'] for t in rows):%Y-%m-%d} to "  # type: ignore[type-var]
          f"{max(t['signal'] for t in rows):%Y-%m-%d}. Costs assumed: {DEFAULT_COST_PIPS} pips.")
    print(f"\nPRE-REGISTERED CANDIDATE, all pairs, NET: {stats(taken, 'net', span)}")
    print(f"                              gross   : {stats(taken, 'gross', span)}")
    net = [float(t["net"]) for t in taken]  # type: ignore[arg-type]
    wins, losses = sum(v for v in net if v > 0), -sum(v for v in net if v < 0)
    passed = bool(net) and sum(net) / len(net) > 0 and losses > 0 and wins / losses > 1
    for symbol in sorted({str(t["symbol"]) for t in taken}):
        print(f"  {symbol}: {stats([t for t in taken if t['symbol'] == symbol], 'net', span)}")
    years: dict[int, list[float]] = defaultdict(list)
    for t in taken:
        years[t["signal"].year].append(float(t["net"]))  # type: ignore[union-attr,arg-type]
    print("  NET by year: " + " | ".join(f"{y} {sum(v) / len(v):+.3f} R ({len(v)})" for y, v in sorted(years.items())))
    print(f"\nVERDICT: {'PASS' if passed else 'FAIL'} (rule: net average R > 0 and net profit factor > 1)")
    print("A pass on one period is evidence, not proof; the untouched final year remains the last check.")


if __name__ == "__main__":
    main()
