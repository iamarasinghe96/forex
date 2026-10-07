"""Explain one closed paper trade from the bot's own records (read-only).

Usage: python scripts/trade_autopsy.py [--symbol USDJPY] [--client-id ID] [--after-hours 24] [--db PATH]

Default: the most recently closed trade. Prints the trade's numbers, why the bot entered, the size
of its stop compared with normal hourly movement, the hour-by-hour path from entry to exit, what
the price did after the exit, and every closed trade so far. The database is opened read-only.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")


def base_symbol(symbol: str) -> str:
    return symbol.upper().split(".")[0]


def r_multiple(price: Decimal, entry: Decimal, risk: Decimal, side: int) -> Decimal:
    return (price - entry) * side / risk


def local(stamp: str) -> str:
    return datetime.fromisoformat(stamp).astimezone(SYDNEY).strftime("%a %d %b %H:%M")


def journal_near(db: sqlite3.Connection, kind: str, symbol: str, at: datetime) -> dict[str, Any] | None:
    """The bot's own record of this entry: same pair, written in the minutes around the fill."""
    rows = db.execute("SELECT payload_json FROM journal_events WHERE kind=? AND observed_at_utc BETWEEN ? AND ? "
                      "ORDER BY sequence DESC", (kind, (at - timedelta(minutes=10)).isoformat(),
                                                 (at + timedelta(minutes=2)).isoformat())).fetchall()
    for (raw,) in rows:
        payload = json.loads(raw)
        if base_symbol(str(payload.get("symbol", ""))) == symbol:
            return payload
    return None


def hourly_atr(bars: list[tuple[str, Decimal, Decimal, Decimal, Decimal]], period: int = 14) -> Decimal | None:
    if len(bars) <= period:
        return None
    ranges = [max(high, prev_close) - min(low, prev_close)
              for (_, _, high, low, _), (_, _, _, _, prev_close) in zip(bars[1:], bars[:-1], strict=True)]
    return sum(ranges[-period:], Decimal(0)) / period


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=None, help="Default: paper.database in config.yaml")
    parser.add_argument("--symbol", default=None, help="Latest closed trade on this pair, e.g. USDJPY")
    parser.add_argument("--client-id", default=None, help="One specific trade")
    parser.add_argument("--after-hours", type=int, default=24, help="Hours of price shown after the exit")
    args = parser.parse_args()
    if args.db is None:
        import yaml
        args.db = Path(yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))["paper"]["database"])
    db = sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True)
    closed = db.execute("SELECT client_id, payload, initial_stop, opened_at, closed_at, close_payload "
                        "FROM paper_positions WHERE closed_at IS NOT NULL ORDER BY closed_at").fetchall()
    chosen = [row for row in closed
              if (args.client_id is None or row[0] == args.client_id)
              and (args.symbol is None or base_symbol(json.loads(row[1])["symbol"]) == base_symbol(args.symbol))]
    if not chosen:
        print("No closed trade matches.")
        return 1
    client_id, raw, initial_raw, opened, closed_at, close_raw = chosen[-1]
    position, outcome = json.loads(raw), json.loads(close_raw)
    symbol = base_symbol(position["symbol"])
    side = 1 if position["side"] == "LONG" else -1
    entry, initial = Decimal(position["entry"]), Decimal(initial_raw)
    exit_price, target = Decimal(str(outcome["exit"])), Decimal(position["target"])
    volume, pnl = Decimal(position["volume"]), Decimal(str(outcome["pnl_aud"]))
    balance_after = Decimal(str(outcome["balance"]))
    risk = abs(entry - initial)
    per_price = Decimal(position["tick_value"]) / Decimal(position["tick_size"]) * volume
    pip = Decimal("0.01") if symbol.endswith("JPY") else Decimal("0.0001")
    opened_at, closed_dt = datetime.fromisoformat(opened), datetime.fromisoformat(closed_at)

    print(f"TRADE {client_id}")
    print(f"  {symbol} {'BUY' if side > 0 else 'SELL'} {volume} lots | opened {opened[:19]} UTC ({local(opened)} Sydney)"
          f" | closed {closed_at[:19]} UTC ({local(closed_at)} Sydney) by {outcome['reason']}")
    print(f"  entry {entry} | first stop {initial} ({risk / pip:.1f} pips) | exit {exit_price} | target {target}")
    print(f"  result {r_multiple(exit_price, entry, risk, side):+.2f} R = A${pnl:+.2f}; balance "
          f"A${balance_after - pnl:.2f} -> A${balance_after:.2f}")
    planned = risk * per_price
    print(f"  planned loss at the stop A${planned:.2f} = {planned / (balance_after - pnl) * 100:.1f}% of the balance")
    beyond = (initial - exit_price) * side
    if beyond > 0:
        print(f"  exit was {beyond / pip:.1f} pips past the stop: the bot checks prices every few seconds and "
              "closes at the first price beyond the stop (bid for a buy, ask for a sell)")

    candidate = journal_near(db, "candidate", symbol, opened_at)
    execution = journal_near(db, "execution", symbol, opened_at)
    features = (candidate or {}).get("analysis", {}).get("feature_snapshot", {})
    print("\nWHY IT ENTERED (the bot's record at the time)")
    if candidate is None:
        print("  No candidate record found near the entry time.")
    else:
        info = candidate.get("candidate", {})
        regime = info.get("h4_regime", {})
        print(f"  style {candidate.get('trade_style')} | setup {info.get('setup_type')} | "
              f"H4 trend strength {regime.get('trend_strength', '?')} | settings {candidate.get('strategy_version')}")
        for name, value in sorted(info.get("setup_strength_components", {}).items()):
            print(f"  component {name}: {value:.2f}")
        if features:
            def num(name: str) -> str:
                value = features.get(name)
                return "?" if value is None else f"{value:.5g}"
            print(f"  H1 range position {num('h1_range_position')} (1 = top of the last 20 hours), "
                  f"20-hour low {num('h1_rolling_low')}, H1 ATR {num('h1_atr')}")
    if execution is not None and execution.get("entry_spread_pips") is not None:
        print(f"  spread at entry {execution['entry_spread_pips']:.1f} pips = {execution.get('entry_spread_r') or 0:.2f} R")

    start = opened_at - timedelta(hours=30)
    end = closed_dt + timedelta(hours=args.after_hours)
    rows = db.execute("SELECT timestamp_utc, open, high, low, close FROM candles WHERE symbol=? AND timeframe='H1' "
                      "AND timestamp_utc BETWEEN ? AND ? ORDER BY timestamp_utc",
                      (symbol, start.isoformat(), end.isoformat())).fetchall()
    bars = [(row[0], *(Decimal(str(v)) for v in row[1:])) for row in rows]
    before = [b for b in bars if datetime.fromisoformat(b[0]) + timedelta(hours=1) <= opened_at]
    atr = Decimal(str(features["h1_atr"])) if "h1_atr" in features else hourly_atr(before)
    print("\nSTOP SIZE")
    if atr:
        print(f"  the stop was {risk / atr:.2f} x the normal hourly range (H1 ATR {atr / pip:.1f} pips). "
              "Under about 1.5 x, ordinary hourly wiggles can reach it.")
    trail = 3 * atr if atr else None
    if trail:
        print(f"  for comparison, the trailing stop used later in a winning trade sits 3 x ATR = {trail / pip:.1f} pips away")

    print("\nHOUR BY HOUR (UTC hour start; R = distance from entry in units of the first stop)")
    print(f"  {'UTC':16} {'Sydney':16} {'high R':>7} {'low R':>7} {'close R':>8}  note")
    during, after = [], []
    for stamp, _, high, low, close in bars:
        when = datetime.fromisoformat(stamp)
        if when + timedelta(hours=1) <= opened_at - timedelta(hours=6):
            continue
        note = ""
        if when <= opened_at < when + timedelta(hours=1):
            note = "<- ENTRY"
        elif when + timedelta(hours=1) <= opened_at:
            note = "before"
        if when <= closed_dt < when + timedelta(hours=1):
            note = (note + " <- STOP HIT").strip() if outcome["reason"] == "STOP" else (note + " <- EXIT").strip()
        elif when > closed_dt:
            note = "after exit"
        best = high if side > 0 else low
        worst = low if side > 0 else high
        if opened_at < when + timedelta(hours=1) and when <= closed_dt:
            during.append((best, worst))
        elif when > closed_dt:
            after.append((best, worst, when))
        print(f"  {stamp[:16]:16} {local(stamp):16} {r_multiple(best, entry, risk, side):+7.2f} "
              f"{r_multiple(worst, entry, risk, side):+7.2f} {r_multiple(close, entry, risk, side):+8.2f}  {note}")

    print("\nWHAT IT MEANS")
    if during:
        print(f"  best point while open: {max(r_multiple(b, entry, risk, side) for b, _ in during):+.2f} R "
              "(hourly highs/lows include the entry hour before the fill, so this can overstate it)")
    if after:
        lowest = min(r_multiple(w, entry, risk, side) for _, w, _ in after)
        highest = max(r_multiple(b, entry, risk, side) for b, _, _ in after)
        back = next((when for b, _, when in after if r_multiple(b, entry, risk, side) >= 0), None)
        print(f"  in the {args.after_hours} hours after the exit: worst {lowest:+.2f} R, best {highest:+.2f} R")
        print("  price came back to the entry price at " + (f"{back:%Y-%m-%d %H:%M} UTC" if back else "no point in that window"))
        if back and lowest > -2:
            print("  -> a stop about twice as wide would have survived this dip, but would also double the A$ size of "
                  "every full loss unless the position is halved; one trade cannot tell which is better")
        elif lowest <= -2:
            print("  -> the price kept falling well past the stop: a wider stop would have lost more")
    else:
        print("  no stored prices after the exit yet (the bot stores hourly bars as they close)")

    print("\nALL CLOSED TRADES")
    total = Decimal(0)
    for cid, raw_p, init, _, done, close_p in closed:
        p, o = json.loads(raw_p), json.loads(close_p)
        e, s = Decimal(p["entry"]), Decimal(init)
        sd = 1 if p["side"] == "LONG" else -1
        r = r_multiple(Decimal(str(o["exit"])), e, abs(e - s), sd) if e != s else Decimal(0)
        total += Decimal(str(o["pnl_aud"]))
        mark = "  <- this trade" if cid == client_id else ""
        print(f"  {done[:16]} {base_symbol(p['symbol']):7} {'BUY ' if sd > 0 else 'SELL'} {o['reason']:6} "
              f"{r:+6.2f} R  A${Decimal(str(o['pnl_aud'])):+8.2f}{mark}")
    print(f"  total A${total:+.2f} over {len(closed)} trades")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
