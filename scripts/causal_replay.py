"""Causal replay of the trend strategy with matched random-entry controls (research only).

Usage (PC or any machine with the Dukascopy research databases):
  python scripts/causal_replay.py --research-database data/dukascopy-2012-2018.sqlite3 --start 2012-04-01
  python scripts/causal_replay.py --research-database data/dukascopy-research.sqlite3 --start 2021-01-01 --end 2025-09-28
Options: --controls 1000 --target-r 1.5 --breakeven-r 1.0 --trail-atr 3 --horizon-bars 0 --profile baseline|config
         --max-gap-hours 48

What it does, in one chronological event stream per pair (no walk-forward windows):
1. Splits each pair's history wherever at least --max-gap-hours weekday trading hours are
   missing (scripts/data_coverage.py lists them). Indicators restart after a hole and no trade
   may span one: a trade still open at a hole is censored (reported, not scored).
2. Runs the live analysis code on every closed H1 bar and records, per hour: the H4 trend
   direction and whether the H4 regime is a trend, the structural stop (20-bar swing), H1 ATR
   and whether the strategy signals (trend setup with confidence >= --min-conviction).
3. Simulates the strategy: one open trade per pair; a trade occupies its pair until it exits.
   With --breakeven-r 1 (the live rule), stops move through the live bot's own
   forex.risk.protective_stop, fed each bar's best price. That is what the paper bot's 5-second
   polling sees: break-even and the ATR trail ratchet only while price is at least +1R.
4. Random controls answer "does the strategy's selection add value?":
   - MATCHED (primary): enter only in H4 trend regimes, in the regime direction, with stop
     widths (risk in ATRs) inside the strategy's own range, at a probability per pair x UTC
     session x stop-width quintile equal to the strategy's own rate there. Same stops, exits
     and costs. Seeds --seed-base + 1,000,000 + k.
   - BROAD (as in earlier runs): any hour with an H4 bias, rate per pair x session. Seeds
     --seed-base + k.
   Results are reported net of costs, at 2x costs, and gross, where gross isolates direction
   skill from cost efficiency.
Costs: assumed round trip 0.9/1.2/1.0 pips (EURUSD/GBPUSD/USDJPY); --cost-scale 2 for stress.
No swap. Bid candles for both sides; costs are subtracted from each trade.
Intrabar order is unknown on H1 data: if stop and target are both touched, the stop is assumed;
stop moves apply from the next bar. A bar that opens beyond the stop (gap) fills at that open.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

COST_PIPS = {"EURUSD": 0.9, "GBPUSD": 1.2, "USDJPY": 1.0}
TREND = "TREND_CONTINUATION_BREAKOUT_PULLBACK"
TREND_LABELS = {"TREND_UP", "TREND_DOWN"}

# (exit index, gross R, cost in R at cost scale 1, censored or still open)
Outcome = tuple[int, float, float, bool]
Trade = tuple[int, float, float, bool]  # (entry index, gross R, cost R, censored or still open)


@dataclass
class Hour:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    direction: int      # +1/-1 from H4 directional bias, 0 when undefined
    stop: float         # structural stop for that direction (nan if unavailable)
    atr: float
    signal: bool        # strategy would enter here
    trend: bool = True  # H4 regime is TREND_UP/TREND_DOWN (the strategy's precondition)
    segment: int = 0    # contiguous-data segment; no trade may span two

    @property
    def risk_atr(self) -> float:
        return (self.close - self.stop) * self.direction / self.atr if self.atr > 0 else float("nan")


def session(hour: int) -> int:
    return 0 if hour < 8 else 1 if hour < 16 else 2


def pip(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def analyse_pair(job: tuple[str, str, str, str, str, float, int]) -> tuple[str, list[Hour], int]:
    from research_db import load_candles, segments

    from forex.analysis import InsufficientDataError, analyse_market, prepare_candles
    from forex.config import AnalysisConfig
    from forex.domain import Timeframe

    symbol, database, config_json, start, end, min_conviction, max_gap = job
    config = AnalysisConfig.model_validate_json(config_json)
    h1_all = load_candles(database, symbol, Timeframe.H1)
    h4_all = load_candles(database, symbol, Timeframe.H4)
    first, last = datetime.fromisoformat(start).replace(tzinfo=UTC), datetime.fromisoformat(end).replace(tzinfo=UTC)
    hours: list[Hour] = []
    parts = segments(h1_all, max_gap)
    for number, h1 in enumerate(parts):
        low, high = h1[0].timestamp_utc, h1[-1].timestamp_utc + timedelta(hours=1)
        if high <= first or low >= last:
            continue
        h4 = [c for c in h4_all if low <= c.timestamp_utc and c.timestamp_utc + timedelta(hours=4) <= high]
        p1, p4 = prepare_candles(h1, config), prepare_candles(h4, config)
        for candle in h1:
            if not first <= candle.timestamp_utc < last:
                continue
            now = candle.timestamp_utc + timedelta(hours=1)
            try:
                result = analyse_market(symbol, p1.closed(now), p4.closed(now), now, config)
            except InsufficientDataError:
                continue  # Warm-up after the start of the data or after a hole.
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
            hours.append(Hour(candle.timestamp_utc, float(candle.open), float(candle.high), float(candle.low),
                              float(candle.close), direction, stop, float(features["h1_atr"]), signal,
                              snap.regime.label.value in TREND_LABELS, number))
    return symbol, hours, len(parts)


def shared_stop(sign: int, entry: float, initial: float, stop: float, price: float, atr: float,
                trail_atr: float | None) -> float:
    """The live bot's stop rule (forex.risk.protective_stop) applied to one observed price."""
    from forex.analysis import Side
    from forex.risk import protective_stop

    result = protective_stop(Side.LONG if sign > 0 else Side.SHORT, Decimal(repr(entry)), Decimal(repr(initial)),
                             Decimal(repr(stop)), Decimal(repr(price)), Decimal(repr(atr)),
                             Decimal(repr(trail_atr)) if trail_atr is not None and atr > 0 else None)
    return float(result.stop)


def outcomes(symbol: str, hours: list[Hour], target_r: float, breakeven_r: float | None,
             trail_atr: float | None, horizon: int) -> list[Outcome | None]:
    """For every hour: the trade if entered at that hour's close, or None if no valid trade."""
    cost = COST_PIPS.get(symbol, 1.0) * pip(symbol)
    live_rule = breakeven_r == 1.0
    result: list[Outcome | None] = []
    for i, h in enumerate(hours):
        risk = (h.close - h.stop) * h.direction
        if h.direction == 0 or not risk > 0:
            result.append(None)
            continue
        entry, sign, stop, initial = h.close, h.direction, h.stop, h.stop
        target = entry + sign * target_r * risk
        reached_be, exit_index, exit_price, still_open = False, len(hours) - 1, hours[-1].close, True
        for j in range(i + 1, len(hours)):
            bar = hours[j]
            if bar.segment != h.segment:  # Data hole: the outcome cannot be observed.
                exit_index, exit_price, still_open = j - 1, hours[j - 1].close, True
                break
            adverse, favourable = (bar.low, bar.high) if sign > 0 else (bar.high, bar.low)
            if (bar.open - stop) * sign <= 0:  # Gapped through the stop: filled at the open, not the stop.
                exit_index, exit_price, still_open = j, bar.open, False
                break
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
            if live_rule:
                if (favourable - entry) * sign >= risk:
                    stop = shared_stop(sign, entry, initial, stop, favourable, bar.atr, trail_atr)
                continue
            if breakeven_r is not None and (favourable - entry) * sign >= breakeven_r * risk:
                reached_be = True
                if (entry - stop) * sign > 0:
                    stop = entry
            if trail_atr is not None and reached_be:
                proposed = bar.close - sign * trail_atr * bar.atr
                if (proposed - stop) * sign > 0:
                    stop = proposed
        result.append((exit_index, (exit_price - entry) * sign / risk, cost / risk, still_open))
    return result


def run(hours: list[Hour], outcome: list[Outcome | None], choose: Callable[[int, Hour], bool]) -> list[Trade]:
    trades: list[Trade] = []
    busy_until = -1
    for i, h in enumerate(hours):
        if i <= busy_until:
            continue
        found = outcome[i]
        if found is None or not choose(i, h):
            continue
        exit_index, gross, cost, still_open = found
        trades.append((i, gross, cost, still_open))
        busy_until = exit_index
    return trades


def net_values(trades: list[Trade], cost_scale: float) -> list[float]:
    return [gross - cost_scale * cost for _, gross, cost, still_open in trades if not still_open]


def summary(trades: list[Trade], cost_scale: float) -> dict[str, float]:
    closed = net_values(trades, cost_scale)
    wins, losses = sum(r for r in closed if r > 0), -sum(r for r in closed if r < 0)
    return {"trades": len(closed), "censored_or_open": len(trades) - len(closed),
            "total_r": round(sum(closed), 2),
            "avg_r": round(sum(closed) / len(closed), 4) if closed else 0.0,
            "pf": round(wins / losses, 3) if losses else float("inf"),
            "win_rate": round(sum(r > 0 for r in closed) / len(closed), 3) if closed else 0.0}


def month_block_ci(streams: dict[str, list[Hour]], trades: dict[str, list[Trade]], cost_scale: float,
                   draws: int = 5000, seed: int = 2026100300) -> tuple[float, float]:
    """95% CI of the mean net R, resampling whole calendar months across all pairs together."""
    by_month: dict[str, list[float]] = defaultdict(list)
    for s, items in trades.items():
        for i, gross, cost, still_open in items:
            if not still_open:
                by_month[streams[s][i].time.strftime("%Y-%m")].append(gross - cost_scale * cost)
    months = list(by_month.values())
    if len(months) < 2:
        return float("nan"), float("nan")
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        values = [r for month in rng.choices(months, k=len(months)) for r in month]
        means.append(statistics.fmean(values) if values else 0.0)
    means.sort()
    return round(means[int(0.025 * draws)], 4), round(means[int(0.975 * draws)], 4)


def entry_rates(streams: dict[str, list[Hour]], exits: dict[str, list[Outcome | None]],
                strategy: dict[str, list[Trade]], eligible: Callable[[Hour], bool],
                cell: Callable[[str, int, Hour], tuple[object, ...]]) -> dict[tuple[object, ...], float]:
    """The strategy's own entry probability per cell, over idle eligible hours."""
    rates: dict[tuple[object, ...], float] = {}
    for s, hours in streams.items():
        seen: dict[tuple[object, ...], int] = defaultdict(int)
        entered: dict[tuple[object, ...], int] = defaultdict(int)
        busy = -1
        entries = {i for i, _, _, _ in strategy[s]}
        for i, h in enumerate(hours):
            found = exits[s][i]
            if i <= busy or found is None or not eligible(h):
                continue
            key = cell(s, i, h)
            seen[key] += 1
            if i in entries:
                entered[key] += 1
                busy = found[0]
        for key, n in seen.items():
            rates[key] = entered[key] / n
    return rates


def controls(streams: dict[str, list[Hour]], exits: dict[str, list[Outcome | None]], count: int, seed: int,
             eligible: Callable[[Hour], bool], cell: Callable[[str, int, Hour], tuple[object, ...]],
             rates: dict[tuple[object, ...], float]) -> list[list[Trade]]:
    runs = []
    for k in range(count):
        rng = random.Random(seed + k)
        trades: list[Trade] = []
        for s, hours in streams.items():
            trades += run(hours, exits[s], lambda i, h, s=s, rng=rng: eligible(h)
                          and rng.random() < rates.get(cell(s, i, h), 0.0))
        runs.append(trades)
    return runs


def compare(strategy: list[Trade], runs: list[list[Trade]], cost_scale: float) -> dict[str, object]:
    out: dict[str, object] = {"n": len(runs)}
    if not runs:
        return out
    for label, scale in (("net", cost_scale), ("gross", 0.0)):
        mine = summary(strategy, scale)
        theirs = [summary(t, scale) for t in runs]
        out[label] = {
            "control_mean_avg_r": round(statistics.fmean(c["avg_r"] for c in theirs), 4),
            "control_mean_trades": round(statistics.fmean(c["trades"] for c in theirs), 1),
            "strategy_avg_r": mine["avg_r"],
            "share_controls_avg_r_at_or_above_strategy": round(
                sum(c["avg_r"] >= mine["avg_r"] for c in theirs) / len(theirs), 4),
            "share_controls_total_r_at_or_above_strategy": round(
                sum(c["total_r"] >= mine["total_r"] for c in theirs) / len(theirs), 4),
        }
    return out


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
    parser.add_argument("--max-gap-hours", type=int, default=48)
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
    jobs = [(s, args.research_database, analysis.model_dump_json(), args.start, args.end, args.min_conviction,
             args.max_gap_hours) for s in symbols]
    from research_db import require_data
    require_data(args.research_database, symbols)
    print(f"Replaying {symbols} from {args.start} ({args.profile} analysis); this takes a while...", flush=True)
    with ProcessPoolExecutor(max_workers=len(jobs)) as pool:
        analysed = list(pool.map(analyse_pair, jobs))
    streams = {s: hours for s, hours, _ in analysed}
    parts = {s: n for s, _, n in analysed}
    for s in symbols:
        print(f"  {s}: {len(streams[s])} hours analysed, {sum(h.signal for h in streams[s])} signal hours, "
              f"{parts[s]} data segment(s)", flush=True)
        if not streams[s]:
            raise SystemExit(f"No {s} hours in {args.start}..{args.end}; check the dates and the database.")
    exits = {s: outcomes(s, streams[s], args.target_r, args.breakeven_r, args.trail_atr, args.horizon_bars)
             for s in symbols}
    scale = args.cost_scale

    # Strategy.
    strategy = {s: run(streams[s], exits[s], lambda i, h: h.signal) for s in symbols}
    every = [t for s in symbols for t in strategy[s]]
    result: dict[str, object] = {
        "settings": vars(args), "data_segments": parts,
        "strategy": {"net": summary(every, scale), "net_2x_costs": summary(every, 2 * scale),
                     "gross": summary(every, 0.0)},
        "strategy_mean_95ci_month_blocks": {"net": month_block_ci(streams, strategy, scale),
                                            "gross": month_block_ci(streams, strategy, 0.0)},
        "strategy_by_pair": {s: summary(strategy[s], scale) for s in symbols},
        "strategy_by_side": {name: summary([t for s in symbols for t in strategy[s]
                                            if streams[s][t[0]].direction == sign], scale)
                             for name, sign in (("long", 1), ("short", -1))},
        "strategy_excluding_jpy": summary([t for s in symbols if "JPY" not in s for t in strategy[s]], scale),
    }
    by_year: dict[int, list[float]] = defaultdict(list)
    for s in symbols:
        for i, gross, cost, still_open in strategy[s]:
            if not still_open:
                by_year[streams[s][i].time.year].append(gross - scale * cost)
    result["strategy_by_year"] = {y: round(statistics.fmean(v), 3) for y, v in sorted(by_year.items())}

    # Matched controls: same regime, session and stop-width quintile as the strategy's entries.
    widths = sorted(streams[s][i].risk_atr for s in symbols for i, *_ in strategy[s])
    edges = [widths[int(len(widths) * q / 5)] for q in range(1, 5)] if len(widths) >= 5 else []
    narrowest, widest = (widths[0], widths[-1]) if widths else (0.0, float("inf"))

    def width_bin(h: Hour) -> int:
        return sum(h.risk_atr > e for e in edges)

    def matched_cell(s: str, i: int, h: Hour) -> tuple[object, ...]:
        return (s, session(h.time.hour), width_bin(h))

    def broad_cell(s: str, i: int, h: Hour) -> tuple[object, ...]:
        return (s, session(h.time.hour))

    def in_trend(h: Hour) -> bool:
        # Also within the strategy's own range of stop widths: a stop far tighter than any the
        # strategy takes would inflate the control's cost per R.
        return h.trend and narrowest <= h.risk_atr <= widest

    def anything(h: Hour) -> bool:
        return True

    matched_rates = entry_rates(streams, exits, strategy, in_trend, matched_cell)
    broad_rates = entry_rates(streams, exits, strategy, anything, broad_cell)
    result["controls_matched"] = compare(every, controls(streams, exits, args.controls, args.seed_base + 1_000_000,
                                                         in_trend, matched_cell, matched_rates), scale)
    result["controls_broad"] = compare(every, controls(streams, exits, args.controls, args.seed_base,
                                                       anything, broad_cell, broad_rates), scale)
    result["stop_width_quintile_edges_atr"] = [round(e, 3) for e in edges]
    print(json.dumps(result, indent=2, default=str))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print("\nRead: in 'controls_matched', a share near 0 means the strategy's selection beats random entries "
          "taken in the same trend regimes, sessions and stop widths; near 0.5 means it adds nothing. "
          "'gross' removes costs, so it isolates direction skill from cost efficiency.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
