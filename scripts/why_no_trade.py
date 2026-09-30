"""Explain what the paper bot decided over a period, per symbol (read-only).

Usage: python scripts/why_no_trade.py --since 2026-09-09 [--until 2026-10-01] [--db data/paper.sqlite3]

Answers "the chart trended - why didn't the bot trade?" from the bot's own journal: how the H4
regime was labelled each hour, why each no-trade happened, and what became of each candidate.
Opens the database read-only; never changes it.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

KINDS = ("no_trade", "candidate", "hard_risk_block", "context_rejection", "execution")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=Path("data/paper.sqlite3"))
    parser.add_argument("--since", required=True, help="UTC date, e.g. 2026-09-09")
    parser.add_argument("--until", default="9999", help="UTC date (exclusive)")
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit(f"Journal not found: {args.db}")
    db = sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True)
    rows = db.execute(
        "SELECT kind, observed_at_utc, payload_json FROM journal_events WHERE mode='PAPER' AND "
        f"kind IN ({','.join('?' * len(KINDS))}) AND observed_at_utc >= ? AND observed_at_utc < ? "
        "ORDER BY observed_at_utc", (*KINDS, args.since, args.until)).fetchall()
    kinds: dict[str, Counter[str]] = defaultdict(Counter)
    regimes: dict[str, Counter[str]] = defaultdict(Counter)
    reasons: dict[str, Counter[str]] = defaultdict(Counter)
    daily: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for kind, observed, raw in rows:
        payload = json.loads(raw)
        symbol = payload.get("symbol", "?")
        kinds[symbol][kind] += 1
        if kind == "no_trade":
            reasons[symbol][str(payload.get("reason"))] += 1
            regime = payload.get("analysis", {}).get("regime", {}).get("label", "?")
            regimes[symbol][regime] += 1
            daily[symbol][observed[:10]][regime] += 1
        elif kind == "candidate":
            regimes[symbol][payload.get("analysis", {}).get("regime", {}).get("label", "?")] += 1
            daily[symbol][observed[:10]]["CANDIDATE"] += 1
    if not rows:
        print("No decisions in that period (was the bot running?).")
        return 0
    for symbol in sorted(kinds):
        total = sum(regimes[symbol].values())
        print(f"\n=== {symbol}: {total} hourly evaluations ===")
        print("Outcomes:", ", ".join(f"{k} {n}" for k, n in kinds[symbol].most_common()))
        print("H4 regime label:", ", ".join(f"{k} {n}" for k, n in regimes[symbol].most_common()))
        print("No-trade reasons:")
        for reason, n in reasons[symbol].most_common():
            print(f"  {n:5d}  {reason}")
        print("By day (regime counts; CANDIDATE = a trade idea was produced):")
        for day in sorted(daily[symbol]):
            print(f"  {day}  " + ", ".join(f"{k} {n}" for k, n in daily[symbol][day].most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
