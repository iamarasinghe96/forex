"""Research only: summarise exported out-of-sample trades (see research_trades.py).

Adds an ASSUMED round-trip cost (spread + commission, in pips) and compares simple candidate
rule sets, both counting every signal and taking one trade at a time per pair (like the bot).
Nothing here changes the bot. Usage:
    .venv\\Scripts\\python.exe scripts\\research_summary.py [--file reports\\backtest\\oos-trades.csv]
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

# Assumed IC Markets raw-account round trip (average spread + ~USD 7/lot commission), in pips.
# Replace with measured values before relying on net results.
DEFAULT_COST_PIPS = {"EURUSD": 0.9, "GBPUSD": 1.2, "USDJPY": 1.0}
LIVE_BANDS = {"LOW", "MEDIUM", "HIGH"}

Row = dict[str, object]
Rule = Callable[[Row], bool]

RULES: list[tuple[str, Rule]] = [
    ("All signals (research baseline)", lambda t: True),
    ("CURRENT BOT: confidence >= 55, all setups", lambda t: t["band"] in LIVE_BANDS),
    ("A: trend setups only, any confidence", lambda t: str(t["setup"]).startswith("TREND")),
    ("A-live: trend only AND confidence >= 55", lambda t: str(t["setup"]).startswith("TREND") and t["band"] in LIVE_BANDS),
    ("B: trend only, skip HIGH volatility", lambda t: str(t["setup"]).startswith("TREND") and t["vol"] != "HIGH"),
    ("C: trend only, SWING style", lambda t: str(t["setup"]).startswith("TREND") and t["style"] == "SWING"),
]


def load(path: Path, cost_pips: dict[str, float], cost_scale: float) -> list[Row]:
    rows: list[Row] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            pip = 0.01 if raw["symbol"].endswith("JPY") else 0.0001
            risk = float(raw["initial_risk"])
            cost_r = cost_pips.get(raw["symbol"], 1.0) * pip * cost_scale / risk if risk > 0 else 0.0
            rows.append({"symbol": raw["symbol"], "signal": datetime.fromisoformat(raw["signal_time_utc"]),
                         "exit": datetime.fromisoformat(raw["exit_time_utc"]), "setup": raw["setup_family"],
                         "band": raw["conviction_band"], "vol": raw["volatility_bucket"], "style": raw["trade_style"],
                         "side": raw["side"], "regime": raw["regime"], "gross": float(raw["gross_r"]),
                         "net": float(raw["gross_r"]) - cost_r, "stop_pips": float(raw["stop_pips"])})
    rows.sort(key=lambda t: t["signal"])  # type: ignore[arg-type,return-value]
    return rows


def one_at_a_time(rows: Iterable[Row]) -> list[Row]:
    """Take a signal only when no earlier taken trade on the same pair is still open."""
    busy_until: dict[str, datetime] = {}
    taken = []
    for t in rows:
        symbol, signal = str(t["symbol"]), t["signal"]
        if symbol in busy_until and signal < busy_until[symbol]:  # type: ignore[operator]
            continue
        busy_until[symbol] = t["exit"]  # type: ignore[assignment]
        taken.append(t)
    return taken


def stats(rows: list[Row], key: str, weeks: float) -> str:
    if not rows:
        return "no trades"
    values = [float(t[key]) for t in rows]  # type: ignore[arg-type]
    wins, losses = sum(v for v in values if v > 0), -sum(v for v in values if v < 0)
    equity = peak = drawdown = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    pf = f"{wins / losses:.2f}" if losses else "n/a"
    return (f"{len(values):>6} trades {len(values) / weeks:>5.1f}/wk | win {sum(v > 0 for v in values) / len(values) * 100:4.1f}% | "
            f"avg {sum(values) / len(values):+.3f} R | total {sum(values):+8.1f} R | PF {pf} | max DD {drawdown:.1f} R")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=Path("reports/backtest/oos-trades.csv"))
    parser.add_argument("--cost-scale", type=float, default=1.0, help="Multiply assumed costs (e.g. 2 for a stress test)")
    args = parser.parse_args()
    rows = load(args.file, DEFAULT_COST_PIPS, args.cost_scale)
    span = (max(t["signal"] for t in rows) - min(t["signal"] for t in rows)).days / 7  # type: ignore[operator]
    by_pair = defaultdict(int)
    for t in rows:
        by_pair[t["symbol"]] += 1
    print(f"{len(rows)} exported trades {dict(by_pair)} over {span:.0f} weeks (out-of-sample, holdout excluded).")
    print(f"Assumed round-trip cost x{args.cost_scale}: {DEFAULT_COST_PIPS} pips. Median stop: "
          f"{sorted(float(t['stop_pips']) for t in rows)[len(rows) // 2]:.1f} pips.\n")  # type: ignore[arg-type]
    print("Setup x confidence band (every signal, gross avg R):")
    cell: dict[tuple[str, str], list[float]] = defaultdict(list)
    for t in rows:
        cell[(str(t["setup"])[:24], str(t["band"]))].append(float(t["gross"]))  # type: ignore[arg-type]
    for (setup, band), values in sorted(cell.items()):
        print(f"  {setup:<24} {band:<14} {len(values):>6} trades  avg {sum(values) / len(values):+.3f} R")
    for name, rule in RULES:
        selected = [t for t in rows if rule(t)]
        sequential = one_at_a_time(selected)
        print(f"\n{name}")
        print(f"  every signal, gross   : {stats(selected, 'gross', span)}")
        print(f"  one at a time, gross  : {stats(sequential, 'gross', span)}")
        print(f"  one at a time, NET    : {stats(sequential, 'net', span)}")
        years: dict[int, list[float]] = defaultdict(list)
        for t in sequential:
            years[t["signal"].year].append(float(t["net"]))  # type: ignore[union-attr,arg-type]
        print("  NET by year           : " + " | ".join(
            f"{year} {sum(v) / len(v):+.3f} R ({len(v)})" for year, v in sorted(years.items())))
    print("\nOne-at-a-time approximates the live bot (it also caps total open trades at 4).")
    print("Choosing a rule after seeing these results is itself fitting: the untouched final year must confirm it.")


if __name__ == "__main__":
    main()
