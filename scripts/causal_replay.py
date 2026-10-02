"""Causal replay of the trend strategy with matched random-entry controls (research only).

Usage (PC or any machine with the Dukascopy research databases):
  python scripts/causal_replay.py --research-database data/dukascopy-2012-2018.sqlite3 --start 2012-04-01
  python scripts/causal_replay.py --research-database data/dukascopy-research.sqlite3 --start 2021-01-01 --end 2025-09-28
Options: --controls 1000 --target-r 1.5 --breakeven-r 1.0 --trail-atr 3 --horizon-bars 0 --profile baseline|config

What it does, in one chronological event stream per pair (no walk-forward windows):
1. Runs the live analysis code on every closed H1 bar and records, per hour: the H4 trend
   direction, the structural stop (20-bar swing), H1 ATR and whether the strategy signals
   (trend setup with confidence >= 55, the "trend55" rule).
2. Simulates the strategy: one open trade per pair; a trade occupies its pair until it exits;
   trades still open at the end are marked at the last close (reported separately). This
   removes the censoring of trades that crossed walk-forward window boundaries.
3. Runs matched random controls (seeds 2026100200...): on every idle, eligible hour a control
   enters with probability p(pair, UTC session) equal to the strategy's own entry rate there,
   in the same contemporaneous H4 direction, with the same stop and exit rules and costs. Only
   the timing differs, so the comparison answers "does our entry timing add value?".
Costs: assumed round trip 0.9/1.2/1.0 pips (EURUSD/GBPUSD/USDJPY); --cost-scale 2 for stress.
Intrabar order is unknown on H1 data: if stop and target are both touched, the stop is assumed.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

COST_PIPS = {"EURUSD": 0.9, "GBPUSD": 1.2, "USDJPY": 1.0}
TREND = "TREND_CONTINUATION_BREAKOUT_PULLBACK"


@dataclass
class Hour:
    time: datetime
    high: float
    low: float
    close: float
    direction: int      # +1/-1 from H4 directional bias, 0 when undefined
    stop: float         # structural stop for that direction (nan if unavailable)
    atr: float
    signal: bool        # strategy (trend55) would enter here


def session(hour: int) -> int:
    return 0 if hour < 8 else 1 if hour < 16 else 2


def pip(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def analyse_pair(job: tuple[str, str, str, str, str, str, float]) -> tuple[str, list[Hour]]:
    from forex.analysis import InsufficientDataError, analyse_market, prepare_candles
    from forex.config import AnalysisConfig
    from forex.domain import Timeframe
    from forex.persistence import CandleStore

    symbol, database, config_json, start, end, _, min_conviction = job
    config = AnalysisConfig.model_validate_json(config_json)
    store = CandleStore(Path(database))
    h1 = store.load(symbol, Timeframe.H1)
    p1, p4 = prepare_candles(h1, config), prepare_candles(store.load(symbol, Timeframe.H4), config)
    first, last = datetime.fromisoformat(start).replace(tzinfo=UTC), datetime.fromisoformat(end).replace(tzinfo=UTC)
    hours: list[Hour] = []
    for candle in h1:
        if not first <= candle.timestamp_utc < last:
            continue
        now = candle.timestamp_utc + timedelta(hours=1)
        try:
            result = analyse_market(symbol, p1.closed(now), p4.closed(now), now, config)
        except InsufficientDataError:
            continue
        snap, features = result.snapshot, result.snapshot.feature_snapshot
        bias = snap.regime.directional_bias
        direction = 1 if bias > 0 else -1 if bias < 0 else 0
        stop = float(features["h1_rolling_low"] if direction > 0 else features["h1_rolling_high"])
        candidate = result.candidate
        signal = bool(candidate is not None and candidate.setup_type.value == TREND
                      and (1 - candidate.uncertainty) * 100 >= min_conviction)
        if signal and candidate is not None:
            direction = 1 if candidate.side.value == "LONG" else -1
            levels = candidate.structural_reference_levels
            stop = float(levels["rolling_low" if direction > 0 else "rolling_high"])
        hours.append(Hour(candle.timestamp_utc, float(candle.high), float(candle.low), float(candle.close),
                          direction, stop, float(features["h1_atr"]), signal))
    return symbol, hours


def outcomes(symbol: str, hours: list[Hour], target_r: float, breakeven_r: float | None,
             trail_atr: float | None, horizon: int, cost_scale: float) -> list[tuple[int, float, bool] | None]:
    """For every hour: (exit index, net R, still_open) if entered at that hour's close, else None."""
    cost = COST_PIPS.get(symbol, 1.0) * pip(symbol) * cost_scale
    result: list[tuple[int, float, bool] | None] = []
    for i, h in enumerate(hours):
        risk = (h.close - h.stop) * h.direction
        if h.direction == 0 or not risk > 0:
            result.append(None)
            continue
        entry, sign, stop = h.close, h.direction, h.stop
        target = entry + sign * target_r * risk
        reached_be, exit_index, exit_price, still_open = False, len(hours) - 1, hours[-1].close, True
        for j in range(i + 1, len(hours)):
            bar = hours[j]
            adverse, favourable = (bar.low, bar.high) if sign > 0 else (bar.high, bar.low)
            if (adverse - stop) * sign <= 0:
                exit_index, exit_price, still_open = j, stop, False
                break
            if (favourable - target) * sign >= 0:
                exit_index, exit_price, still_open = j, target, False
                break
            if horizon and j - i >= horizon:
                exit_index, exit_price, still_open = j, bar.close, False
                break
            # Stop updates apply after the bar (no favourable intrabar ordering).
            if breakeven_r is not None and (favourable - entry) * sign >= breakeven_r * risk:
                reached_be = True
                if (entry - stop) * sign > 0:
                    stop = entry
            if trail_atr is not None and reached_be:
                proposed = bar.close - sign * trail_atr * bar.atr  # Latest ATR, as the live bot.
                if (proposed - stop) * sign > 0:
                    stop = proposed
        result.append((exit_index, ((exit_price - entry) * sign - cost) / risk, still_open))
    return result


def run(hours: list[Hour], outcome: list, choose) -> list[tuple[int, float, bool]]:  # type: ignore[no-untyped-def]
    trades, busy_until = [], -1
    for i, h in enumerate(hours):
        if i <= busy_until or outcome[i] is None or not choose(i, h):
            continue
        exit_index, r, still_open = outcome[i]
        trades.append((i, r, still_open))
        busy_until = exit_index
    return trades


def summary(trades: list[tuple[int, float, bool]]) -> dict[str, float]:
    closed = [r for _, r, still_open in trades if not still_open]
    wins, losses = sum(r for r in closed if r > 0), -sum(r for r in closed if r < 0)
    return {"trades": len(closed), "open_at_end": len(trades) - len(closed), "total_r": round(sum(closed), 2),
            "avg_r": round(sum(closed) / len(closed), 4) if closed else 0.0,
            "pf": round(wins / losses, 3) if losses else float("inf"),
            "win_rate": round(sum(r > 0 for r in closed) / len(closed), 3) if closed else 0.0,
            "open_marked_r": round(sum(r for _, r, o in trades if o), 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--research-database", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", default="2100-01-01")
    parser.add_argument("--controls", type=int, default=1000)
    parser.add_argument("--seed-base", type=int, default=2026100200)
    parser.add_argument("--target-r", type=float, default=1.5)
    parser.add_argument("--breakeven-r", type=float, default=1.0)
    parser.add_argument("--trail-atr", type=float, default=None)
    parser.add_argument("--horizon-bars", type=int, default=0, help="0 = no time exit (as live)")
    parser.add_argument("--cost-scale", type=float, default=1.0)
    parser.add_argument("--min-conviction", type=float, default=55.0)
    parser.add_argument("--profile", choices=["baseline", "config"], default="baseline",
                        help="baseline = analysis used by the 13-year trend55 tests; config = config.yaml as is")
    parser.add_argument("--out", default=None, help="Optional JSON file for the full result")
    args = parser.parse_args()

    from forex.config import AnalysisConfig, load_config
    config = load_config(Path(args.config))
    changes: dict[str, object] = {"allowed_setups": [TREND]}
    if args.profile == "baseline":
        changes.update(high_volatility_blocks_trend=True, trend_efficiency_window=None)
    analysis = AnalysisConfig.model_validate({**config.analysis.model_dump(), **changes})
    symbols = [s.upper() for s in config.broker.symbols]
    jobs = [(s, args.research_database, analysis.model_dump_json(), args.start, args.end, "", args.min_conviction)
            for s in symbols]
    print(f"Replaying {symbols} from {args.start} ({args.profile} analysis); this takes a while...", flush=True)
    with ProcessPoolExecutor(max_workers=len(jobs)) as pool:
        streams = dict(pool.map(analyse_pair, jobs))
    exits = {s: outcomes(s, streams[s], args.target_r, args.breakeven_r, args.trail_atr,
                         args.horizon_bars, args.cost_scale) for s in symbols}

    # Strategy.
    strategy = {s: run(streams[s], exits[s], lambda i, h: h.signal) for s in symbols}
    all_trades = [t for s in symbols for t in strategy[s]]
    result: dict[str, object] = {"exit_model": vars(args), "strategy": summary(all_trades),
                                 "strategy_by_pair": {s: summary(strategy[s]) for s in symbols}}
    by_year: dict[int, list[float]] = defaultdict(list)
    for s in symbols:
        for i, r, still_open in strategy[s]:
            if not still_open:
                by_year[streams[s][i].time.year].append(r)
    result["strategy_by_year"] = {y: round(sum(v) / len(v), 3) for y, v in sorted(by_year.items())}

    # Entry probability per pair and session, from the strategy's own entries on idle eligible hours.
    rates: dict[tuple[str, int], float] = {}
    for s in symbols:
        eligible: dict[int, int] = defaultdict(int)
        entered: dict[int, int] = defaultdict(int)
        busy = -1
        entries = {i for i, _, _ in strategy[s]}
        exit_of = {i: exits[s][i][0] for i in entries}  # type: ignore[index]
        for i, h in enumerate(streams[s]):
            if i <= busy or exits[s][i] is None:
                continue
            eligible[session(h.time.hour)] += 1
            if i in entries:
                entered[session(h.time.hour)] += 1
                busy = exit_of[i]
        for k in range(3):
            rates[(s, k)] = entered[k] / eligible[k] if eligible[k] else 0.0

    controls = []
    for n in range(args.controls):
        rng = random.Random(args.seed_base + n)
        trades = []
        for s in symbols:
            trades += run(streams[s], exits[s], lambda i, h, s=s, rng=rng: rng.random() < rates[(s, session(h.time.hour))])
        controls.append(summary(trades))
    totals = [c["total_r"] for c in controls]
    strat_total = result["strategy"]["total_r"]  # type: ignore[index]
    beaten = sum(t >= strat_total for t in totals)
    strat_avg = result["strategy"]["avg_r"]  # type: ignore[index]
    beaten_avg = sum(c["avg_r"] >= strat_avg for c in controls)
    result["controls"] = {
        "n": len(controls), "mean_total_r": round(statistics.fmean(totals), 2) if totals else None,
        "sd_total_r": round(statistics.pstdev(totals), 2) if totals else None,
        "mean_trades": round(statistics.fmean(c["trades"] for c in controls), 1) if controls else None,
        "mean_avg_r": round(statistics.fmean(c["avg_r"] for c in controls), 4) if controls else None,
        "share_of_controls_at_or_above_strategy": round(beaten / len(controls), 4) if controls else None,
        "share_of_controls_avg_r_at_or_above_strategy": round(beaten_avg / len(controls), 4) if controls else None,
        "entry_rates": {f"{s}|session{k}": round(v, 5) for (s, k), v in rates.items()},
    }
    print(json.dumps(result, indent=2, default=str))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("\nRead: 'share_of_controls_at_or_above_strategy' near 0 means the timing beats random entries "
          "with the same direction, stops, exits and costs; near 0.5 means the timing adds nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
