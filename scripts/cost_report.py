"""Compare the broker's real costs with the research assumptions (read-only).

Usage: python scripts/cost_report.py [--db data/paper-a1000.sqlite3]

1. Spreads the bot sampled every cycle (pips), per pair and per UTC hour, against the research's
   assumed round-trip cost (0.9/1.2/1.0 pips EURUSD/GBPUSD/USDJPY, which also had to cover
   commission and slippage). Buying at the ask and selling at the bid pays the spread once per trade.
2. The spread paid at each actual paper entry, in pips and as a fraction of the trade's risk (R).
3. Overnight swap: the broker's published rates, and what they would have cost the paper trades.
   The paper account does not charge swap, so this is the missing piece of its P&L.

Needs a few days of the bot running with the cost recorder (src/forex/costs.py). Opens the
database read-only.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ASSUMED_PIPS = {"EURUSD": 0.9, "GBPUSD": 1.2, "USDJPY": 1.0}  # scripts/causal_replay.py COST_PIPS
NEW_YORK = ZoneInfo("America/New_York")


def rollover_nights(opened: datetime, closed: datetime, triple_day: int) -> int:
    """Swap nights charged between two instants: one per 17:00 New York rollover Monday-Friday,
    three on the broker's triple day (MT5 numbering 0 = Sunday)."""
    nights = 0
    day = opened.astimezone(NEW_YORK).replace(hour=17, minute=0, second=0, microsecond=0)
    while day <= closed:
        if day > opened and day.weekday() < 5:
            nights += 3 if (day.weekday() + 1) % 7 == triple_day else 1
        day = (day + timedelta(days=1)).replace(hour=17)
    return nights


def spreads(db: sqlite3.Connection) -> None:
    rows = db.execute("SELECT symbol, hour_utc, samples, mean_pips, median_pips, p90_pips, max_pips "
                      "FROM cost_hours ORDER BY symbol, hour_utc").fetchall()
    if not rows:
        print("No spread samples yet. Deploy the cost recorder and let the bot run for a few days.")
        return
    print(f"Spreads sampled {rows[0][1][:16]} to {max(r[1] for r in rows)[:16]} UTC (pips)")
    print(f"{'pair':8} {'hours':>5} {'mean':>6} {'median':>7} {'p90':>6} {'max':>6}  research assumed")
    by_pair: dict[str, list[tuple]] = defaultdict(list)
    for row in rows:
        by_pair[row[0]].append(row)
    for pair, items in by_pair.items():
        samples = sum(r[2] for r in items)
        mean = sum(r[3] * r[2] for r in items) / samples
        print(f"{pair:8} {len(items):5} {mean:6.2f} {statistics.median(r[4] for r in items):7.2f} "
              f"{statistics.median(r[5] for r in items):6.2f} {max(r[6] for r in items):6.1f}  "
              f"{ASSUMED_PIPS.get(pair, float('nan')):.1f} (spread + commission + slippage)")
    print("\nMedian spread by UTC hour of day (the bot evaluates and enters at the start of each hour):")
    pairs = list(by_pair)
    print("hour " + " ".join(f"{p:>8}" for p in pairs))
    for hour in range(24):
        cells = []
        for pair in pairs:
            values = [r[4] for r in by_pair[pair] if int(r[1][11:13]) == hour]
            cells.append(f"{statistics.median(values):8.2f}" if values else f"{'-':>8}")
        print(f"{hour:02d}   " + " ".join(cells))


def entry_spreads(db: sqlite3.Connection) -> None:
    print("\nSpread paid at actual paper entries")
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='journal_events'").fetchone():
        print("No journal in this database.")
        return
    filled = {r[0] for r in db.execute("SELECT client_id FROM paper_positions").fetchall()}
    rows = db.execute("SELECT payload_json FROM journal_events WHERE mode='PAPER' AND kind='execution' "
                      "ORDER BY sequence").fetchall()
    by_pair: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for (raw,) in rows:
        event = json.loads(raw)
        client = (event.get("record") or {}).get("client_id")
        if client in filled and event.get("entry_spread_r") is not None:
            by_pair[str(event["symbol"])].append((event["entry_spread_pips"], event["entry_spread_r"]))
    if not by_pair:
        print("No entries recorded with a spread yet.")
        return
    for pair, items in sorted(by_pair.items()):
        pips, rs = [p for p, _ in items], [r for _, r in items]
        print(f"{pair:8} {len(items):3} entries: mean {statistics.fmean(pips):.2f} pips, "
              f"mean {statistics.fmean(rs):.3f} R, worst {max(rs):.3f} R per trade")


def swaps(db: sqlite3.Connection) -> None:
    rates = {}
    for symbol, long_, short, mode, triple in db.execute(
            "SELECT symbol, swap_long, swap_short, swap_mode, swap_triple_day FROM cost_hours "
            "WHERE swap_mode IS NOT NULL ORDER BY hour_utc").fetchall():
        rates[symbol] = (long_, short, mode, triple)  # Latest published rate wins.
    print("\nOvernight swap (broker's latest published rates)")
    if not rates:
        print("No swap rates recorded yet.")
        return
    for pair, (long_, short, mode, triple) in sorted(rates.items()):
        print(f"{pair:8} long {long_:+.2f}  short {short:+.2f}  mode {mode}  triple day {triple} (0 = Sunday)")
    total_swap = total_pnl = Decimal(0)
    swap_r: list[float] = []
    skipped = 0
    for payload, initial_stop, opened, closed, close_payload in db.execute(
            "SELECT payload, initial_stop, opened_at, closed_at, close_payload FROM paper_positions").fetchall():
        p = json.loads(payload)
        pair = str(p["symbol"]).upper().split(".")[0]
        if pair not in rates or rates[pair][2] != 1:
            skipped += 1  # Only MT5 swap mode 1 (points per lot per night) is converted.
            continue
        long_, short, _, triple = rates[pair]
        end = datetime.fromisoformat(closed) if closed else datetime.now().astimezone()
        nights = rollover_nights(datetime.fromisoformat(opened), end, triple)
        # Assumes tick size equals the point (true for IC Markets forex symbols).
        per_point = Decimal(p["tick_value"]) * Decimal(p["volume"])
        cost = Decimal(str(long_ if p["side"] == "LONG" else short)) * per_point * nights
        risk = abs(Decimal(p["entry"]) - Decimal(initial_stop)) / Decimal(p["tick_size"]) * per_point
        total_swap += cost
        if closed:
            total_pnl += Decimal(str(json.loads(close_payload)["pnl_aud"]))
        if risk > 0:
            swap_r.append(float(cost / risk))
    trades = len(swap_r)
    print(f"Applied to {trades} paper trades (open ones up to now): swap A${total_swap:+.2f} in total, "
          f"mean {statistics.fmean(swap_r) if swap_r else 0:+.3f} R per trade. "
          f"Closed-trade P&L without swap: A${total_pnl:+.2f}."
          + (f" {skipped} trades skipped (no rate or non-point swap mode)." if skipped else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=None, help="Default: paper.database in config.yaml")
    args = parser.parse_args()
    if args.db is None:
        import yaml
        args.db = Path(yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))["paper"]["database"])
    if not args.db.is_file():
        raise SystemExit(f"Paper database not found: {args.db.resolve()}")
    db = sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='cost_hours'").fetchone():
        print("This database has no cost_hours table yet: deploy the cost recorder and restart the bot.")
        return 0
    spreads(db)
    entry_spreads(db)
    swaps(db)
    print("\nCommission is not visible through MT5 symbol data. A Raw-spread account charges it per lot "
          "per side (see the account's contract specifications); a Standard account has none but wider spreads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
