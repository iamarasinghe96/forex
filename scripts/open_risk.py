"""Show each open paper trade's risk and exit plan (read-only).

Usage: python scripts/open_risk.py [--db data/paper-a1000.sqlite3]

For every open position: entry, latest price (from the bot's last heartbeat), initial and current
stop, target, open P&L, the P&L if the current stop were hit now, and which exit stage it is in
(waiting for +1R, stop at entry, or trailing). The database is opened read-only.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from decimal import Decimal
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=None, help="Default: paper.database in config.yaml")
    args = parser.parse_args()
    if args.db is None:
        import yaml
        args.db = Path(yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))["paper"]["database"])
    db = sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True)
    rows = db.execute("SELECT payload, initial_stop, opened_at FROM paper_positions "
                      "WHERE closed_at IS NULL ORDER BY opened_at").fetchall()
    balance = Decimal(db.execute("SELECT balance FROM paper_account WHERE id=1").fetchone()[0])
    health = db.execute("SELECT payload_json, observed_at_utc FROM journal_events WHERE kind='health' "
                        "ORDER BY sequence DESC LIMIT 1").fetchone()
    prices = {}
    if health:
        for item in json.loads(health[0]).get("positions", []):
            prices[item["client_id"]] = Decimal(item["market_price"])
        print(f"Prices from the bot's last update at {health[1][:19]} UTC. Balance A${balance:.2f}.")
    if not rows:
        print("No open trades.")
        return 0
    totals = {"open": Decimal(0), "at_stop": Decimal(0), "at_target": Decimal(0), "initial_risk": Decimal(0)}
    for payload, initial_stop, opened in rows:
        p = json.loads(payload)
        side = 1 if p["side"] == "LONG" else -1
        entry, stop, target = Decimal(p["entry"]), Decimal(p["stop"]), Decimal(p["target"])
        first_stop, volume = Decimal(initial_stop), Decimal(p["volume"])
        per_unit = Decimal(p["tick_value"]) / Decimal(p["tick_size"]) * volume

        def pnl(price: Decimal, entry: Decimal = entry, side: int = side, per_unit: Decimal = per_unit) -> Decimal:
            return (price - entry) * side * per_unit

        price = prices.get(p["client_id"])
        risk = abs(entry - first_stop)
        progress = (price - entry) * side / risk if price is not None and risk else None
        stage = ("trailing / stop at entry or better" if (stop - entry) * side >= 0
                 else "waiting for +1R (original stop)")
        print(f"\n{p['symbol']} {'BUY' if side > 0 else 'SELL'} {volume} lots, opened {opened[:16]} UTC")
        print(f"  entry {entry}  now {price if price is not None else '?'}"
              + (f"  ({progress:+.2f} R)" if progress is not None else ""))
        print(f"  stop: initial {first_stop}, current {stop}  |  target {target}  |  stage: {stage}")
        print(f"  open P&L A${pnl(price):+.2f}" if price is not None else "  open P&L unknown")
        print(f"  if the current stop is hit: A${pnl(stop):+.2f}   if the target is hit: A${pnl(target):+.2f}"
              f"   (initial risk A${pnl(first_stop):+.2f})")
        totals["open"] += pnl(price) if price is not None else 0
        totals["at_stop"] += pnl(stop)
        totals["at_target"] += pnl(target)
        totals["initial_risk"] += pnl(first_stop)
    print(f"\nALL OPEN TRADES: open P&L A${totals['open']:+.2f} | if every current stop is hit "
          f"A${totals['at_stop']:+.2f} | if every target is hit A${totals['at_target']:+.2f} | "
          f"risk when opened A${totals['initial_risk']:+.2f}")
    print("Exits are price-based only (stop, trailing stop, target); there is no time limit. Gaps or a "
          "weekend can close a trade beyond its stop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
