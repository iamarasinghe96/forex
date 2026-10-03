"""Swing-structure breakout test: the classic chart rules, with matched random controls (research only).

Usage (PC with the Dukascopy research databases):
  python scripts/swing_structure.py --research-database data/rebuilt/dukascopy-2012-2018.sqlite3 --start 2012-04-01 --end 2019-01-01
  python scripts/swing_structure.py --research-database data/rebuilt/dukascopy-research.sqlite3 --start 2019-01-01
Options: --timeframe H4|D1 (default H4) --controls 1000 --cost-scale 1 --out result.json

Rules (pre-registered in BUILD_PROGRESS.md "Pre-registration 4"; fixed before any real data was run):
1. Swing points: a bar whose high (low) is above (below) the 2 bars before and the 2 bars after.
   It is only known 2 bars later, when it is confirmed.
2. Larger trend (Dow theory): uptrend when the last two confirmed swing highs AND the last two
   confirmed swing lows are each higher than the one before; downtrend is the mirror image.
3. Consolidation ("rectangle" / "handle"): the 10 bars before the signal bar span at most
   3 x ATR(14).
4. Entry: in an uptrend, a bar closes above the consolidation high (short: below its low in a
   downtrend). Filled at that close.
5. Stop: the other side of the consolidation (long: its low), but never closer than 1 x ATR(14)
   to the entry (a stop inside normal noise; it also keeps R from exploding on tiny risks).
6. Exit: "sell when price drops below a prior low". Every swing low confirmed after entry that is
   above the current stop becomes the new stop (short: swing highs). No profit target.
7. One open trade per pair. Costs: round trip 0.9/1.2/1.0 pips (EURUSD/GBPUSD/USDJPY). A bar that
   opens beyond the stop fills at its open.

Controls answer "does the pattern's timing matter?": on idle bars in the same trend state, a
control enters at random (same rate per pair as the strategy), with the same stop construction
(10-bar consolidation edge) and the same swing-low trailing exit. Only the pattern requirement
(tight consolidation + breakout close) is removed. Seeds 2026100400 onward.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

COST_PIPS = {"EURUSD": 0.9, "GBPUSD": 1.2, "USDJPY": 1.0}
PIVOT = 2           # Bars each side of a swing point.
BOX = 10            # Consolidation length in bars.
BOX_ATR = 3.0       # Maximum consolidation height in ATRs.
MIN_STOP_ATR = 1.0  # Stop at least this many ATRs from the entry.
ATR_PERIOD = 14


@dataclass
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float


def pip(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def daily(bars: list[Bar]) -> list[Bar]:
    """UTC-day bars from H4 bars (the 20:00-24:00 bar straddles the New York close; approximate)."""
    days: dict[object, list[Bar]] = {}
    for b in bars:
        days.setdefault(b.time.date(), []).append(b)
    return [Bar(group[0].time.replace(hour=0), group[0].open, max(b.high for b in group),
                min(b.low for b in group), group[-1].close) for group in days.values()]


def atr(bars: list[Bar], period: int = ATR_PERIOD) -> list[float]:
    """Simple average true range over the last ``period`` bars, as of each bar's close (nan early)."""
    ranges = [bars[0].high - bars[0].low] + [max(b.high, a.close) - min(b.low, a.close)
                                             for a, b in itertools.pairwise(bars)]
    out = [float("nan")] * len(bars)
    for i in range(period - 1, len(bars)):
        out[i] = sum(ranges[i - period + 1:i + 1]) / period
    return out


def confirmed_pivots(bars: list[Bar]) -> tuple[list[float | None], list[float | None]]:
    """(high, low) of the swing point confirmed at each bar's close, or None."""
    highs: list[float | None] = [None] * len(bars)
    lows: list[float | None] = [None] * len(bars)
    for p in range(PIVOT, len(bars) - PIVOT):
        side = bars[p - PIVOT:p] + bars[p + 1:p + PIVOT + 1]
        if all(bars[p].high > b.high for b in side):
            highs[p + PIVOT] = bars[p].high
        if all(bars[p].low < b.low for b in side):
            lows[p + PIVOT] = bars[p].low
    return highs, lows


@dataclass
class State:
    trend: int          # +1 uptrend, -1 downtrend, 0 neither (as of this bar's close)
    box_high: float     # Consolidation over the BOX bars before this one.
    box_low: float
    tight: bool         # Consolidation height <= BOX_ATR x ATR.
    signal: int         # +1 long breakout, -1 short breakout, 0 none
    atr: float          # ATR(14) as of this bar's close.


def states(bars: list[Bar]) -> list[State | None]:
    ranges = atr(bars)
    highs, lows = confirmed_pivots(bars)
    swing_h: list[float] = []
    swing_l: list[float] = []
    out: list[State | None] = []
    for i, bar in enumerate(bars):
        if highs[i] is not None:
            swing_h.append(highs[i])  # type: ignore[arg-type]
        if lows[i] is not None:
            swing_l.append(lows[i])  # type: ignore[arg-type]
        if i < BOX + 1 or len(swing_h) < 2 or len(swing_l) < 2 or ranges[i - 1] != ranges[i - 1]:
            out.append(None)
            continue
        up = swing_h[-1] > swing_h[-2] and swing_l[-1] > swing_l[-2]
        down = swing_h[-1] < swing_h[-2] and swing_l[-1] < swing_l[-2]
        trend = 1 if up else -1 if down else 0
        box = bars[i - BOX:i]
        high, low = max(b.high for b in box), min(b.low for b in box)
        tight = high - low <= BOX_ATR * ranges[i - 1]
        signal = (1 if trend > 0 and tight and bar.close > high else
                  -1 if trend < 0 and tight and bar.close < low else 0)
        out.append(State(trend, high, low, tight, signal, ranges[i]))
    return out


def outcomes(symbol: str, bars: list[Bar], st: list[State | None], cost_scale: float
             ) -> list[tuple[int, float, bool] | None]:
    """For every bar: (exit index, net R, still_open) for a trade in its trend direction, else None."""
    cost = COST_PIPS.get(symbol, 1.0) * pip(symbol) * cost_scale
    highs, lows = confirmed_pivots(bars)
    result: list[tuple[int, float, bool] | None] = []
    for i, s in enumerate(st):
        if s is None or s.trend == 0:
            result.append(None)
            continue
        sign, entry = s.trend, bars[i].close
        stop = s.box_low if sign > 0 else s.box_high
        if (entry - stop) * sign < MIN_STOP_ATR * s.atr:
            stop = entry - sign * MIN_STOP_ATR * s.atr
        risk = (entry - stop) * sign
        if not risk > 0:
            result.append(None)
            continue
        exit_index, exit_price, still_open = len(bars) - 1, bars[-1].close, True
        for j in range(i + 1, len(bars)):
            b = bars[j]
            if (b.open - stop) * sign <= 0:
                exit_index, exit_price, still_open = j, b.open, False
                break
            if ((b.low if sign > 0 else b.high) - stop) * sign <= 0:
                exit_index, exit_price, still_open = j, stop, False
                break
            pivot = lows[j] if sign > 0 else highs[j]  # Confirmed at this close; applies from the next bar.
            if pivot is not None and (pivot - stop) * sign > 0:
                stop = pivot
        result.append((exit_index, ((exit_price - entry) * sign - cost) / risk, still_open))
    return result


def run(n: int, outcome: list, choose) -> list[tuple[int, float, bool]]:  # type: ignore[no-untyped-def]
    trades, busy = [], -1
    for i in range(n):
        if i <= busy or outcome[i] is None or not choose(i):
            continue
        trades.append((i, outcome[i][1], outcome[i][2]))
        busy = outcome[i][0]
    return trades


def summary(trades: list[tuple[int, float, bool]], years: float) -> dict[str, float]:
    closed = [r for _, r, o in trades if not o]
    gains, losses = sum(r for r in closed if r > 0), -sum(r for r in closed if r < 0)
    return {"trades": len(closed), "open_at_end": len(trades) - len(closed),
            "avg_r": round(statistics.fmean(closed), 4) if closed else 0.0,
            "total_r": round(sum(closed), 2), "r_per_year": round(sum(closed) / years, 2) if years else 0.0,
            "pf": round(gains / losses, 3) if losses else float("inf"),
            "win_rate": round(sum(r > 0 for r in closed) / len(closed), 3) if closed else 0.0,
            "median_r": round(statistics.median(closed), 3) if closed else 0.0,
            "best_r": round(max(closed), 2) if closed else 0.0}


def bootstrap_ci(values: list[float], draws: int = 5000, seed: int = 2026100400) -> tuple[float, float]:
    if len(values) < 2:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(draws))
    return round(means[int(0.025 * draws)], 4), round(means[int(0.975 * draws)], 4)


def load(database: str, symbol: str, timeframe: str) -> list[Bar]:
    from research_db import load_candles

    from forex.domain import Timeframe
    bars = [Bar(c.timestamp_utc, float(c.open), float(c.high), float(c.low), float(c.close))
            for c in load_candles(database, symbol, Timeframe.H4)]
    return daily(bars) if timeframe == "D1" else bars


def evaluate(series: dict[str, list[Bar]], start: datetime, end: datetime, controls: int,
             cost_scale: float) -> dict[str, object]:
    """Strategy and matched random controls; entries only inside [start, end), exits may run later."""
    years = (min(end, max(b[-1].time for b in series.values())) - start).days / 365.25
    st = {s: states(bars) for s, bars in series.items()}
    exits = {s: outcomes(s, bars, st[s], cost_scale) for s, bars in series.items()}
    inside = {s: [start <= b.time < end for b in bars] for s, bars in series.items()}
    strategy = {s: run(len(series[s]), exits[s],
                       lambda i, s=s: inside[s][i] and st[s][i] is not None and st[s][i].signal != 0)  # type: ignore[union-attr]
                for s in series}
    rates = {}
    for s, bars in series.items():
        entries = {i for i, _, _ in strategy[s]}
        eligible, busy = 0, -1
        for i in range(len(bars)):
            if i <= busy or not inside[s][i] or exits[s][i] is None:
                continue
            eligible += 1
            if i in entries:
                busy = exits[s][i][0]  # type: ignore[index]
        rates[s] = len(entries) / eligible if eligible else 0.0
    every = [t for s in series for t in strategy[s]]
    closed = [r for _, r, o in every if not o]
    result: dict[str, object] = {
        "strategy": summary(every, years), "mean_r_95ci": bootstrap_ci(closed),
        "by_pair": {s: summary(strategy[s], years) for s in series},
        "avg_bars_held": round(statistics.fmean(exits[s][i][0] - i for s in series  # type: ignore[index]
                                                for i, _, o in strategy[s] if not o), 1) if closed else 0,
    }
    by_year: dict[int, list[float]] = defaultdict(list)
    for s in series:
        for i, r, o in strategy[s]:
            if not o:
                by_year[series[s][i].time.year].append(r)
    result["by_year"] = {y: {"trades": len(v), "avg_r": round(statistics.fmean(v), 3)} for y, v in sorted(by_year.items())}
    runs = []
    for n in range(controls):
        rng = random.Random(2026100400 + n)
        trades = []
        for s, bars in series.items():
            trades += run(len(bars), exits[s], lambda i, s=s, rng=rng: inside[s][i] and rng.random() < rates[s])
        runs.append(summary(trades, years))
    if runs:
        strat = result["strategy"]
        result["controls"] = {
            "n": len(runs), "mean_avg_r": round(statistics.fmean(c["avg_r"] for c in runs), 4),
            "mean_total_r": round(statistics.fmean(c["total_r"] for c in runs), 2),
            "mean_trades": round(statistics.fmean(c["trades"] for c in runs), 1),
            "share_at_or_above_strategy_avg_r": round(sum(c["avg_r"] >= strat["avg_r"] for c in runs) / len(runs), 4),  # type: ignore[index]
            "share_at_or_above_strategy_total_r": round(sum(c["total_r"] >= strat["total_r"] for c in runs) / len(runs), 4),  # type: ignore[index]
            "entry_rate_per_bar": {s: round(v, 5) for s, v in rates.items()},
        }
    return result


def verdict(result: dict[str, object]) -> str:
    """Pre-registered pass rule for one period (Pre-registration 4)."""
    strat, controls = result["strategy"], result.get("controls") or {}
    checks = {"at least 100 closed trades": strat["trades"] >= 100,  # type: ignore[index]
              "mean net R > 0": strat["avg_r"] > 0,  # type: ignore[index]
              "beats >= 95% of random controls on mean R": controls.get("share_at_or_above_strategy_avg_r", 1) <= 0.05}  # type: ignore[union-attr]
    return "; ".join(f"{k}: {'yes' if v else 'NO'}" for k, v in checks.items()) + \
        (" -> PASS for this period" if all(checks.values()) else " -> FAIL for this period")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--research-database", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", default="2100-01-01")
    parser.add_argument("--timeframe", choices=["H4", "D1"], default="H4")
    parser.add_argument("--symbols", default="EURUSD,GBPUSD,USDJPY")
    parser.add_argument("--controls", type=int, default=1000)
    parser.add_argument("--cost-scale", type=float, default=1.0)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    from research_db import require_data
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    require_data(args.research_database, symbols)
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    series = {s: load(args.research_database, s, args.timeframe) for s in symbols}
    for s, bars in series.items():
        print(f"  {s}: {len(bars)} {args.timeframe} bars, {bars[0].time:%Y-%m-%d} to {bars[-1].time:%Y-%m-%d}", flush=True)
    result = evaluate(series, start, end, args.controls, args.cost_scale)
    result["settings"] = {**vars(args), "pivot": PIVOT, "box": BOX, "box_atr": BOX_ATR, "min_stop_atr": MIN_STOP_ATR}
    print(json.dumps(result, indent=2, default=str))
    print("\n" + verdict(result))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
