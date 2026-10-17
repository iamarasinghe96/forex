"""Simulate signals under the paper bot's rules, compare with random directions, report and store.

Conventions (as in scripts/causal_replay.py, the earlier research):
- entry at the signal bar's close; costs (assumed round trip, in pips) are subtracted from each trade;
- exits: the stop, the target, an optional time limit. Break-even and the ATR trail use the live rule
  (forex.risk.protective_stop): once a bar's best price is at least the break-even distance (+1R),
  the stop moves to entry and trails that best price by the ATR multiple;
- stop moves apply from the next bar; if the stop and target are both touched in one bar, the stop
  is assumed; a bar that opens beyond the stop fills at that open;
- a trade cannot cross a data hole: it is "censored" and left out of the results;
- portfolio rules as live: one trade per pair, and the US-dollar cap (open risk in one US-dollar
  direction, at current stops, may not exceed the cap; trades at break-even count as 0).
"""

from __future__ import annotations

import csv
import random
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import sqrt
from pathlib import Path
from typing import Any

from forex.lab.data import History, Series
from forex.lab.settings import LabSettings, Rules
from forex.lab.strategies import STRATEGIES, Context, Signal

HOUR = timedelta(hours=1)
CLUSTER_HOURS = 24  # Same-side signals on a pair this close together count as one decision.


def pip(symbol: str) -> float:
    return 0.01 if symbol.upper().endswith("JPY") else 0.0001


@dataclass(frozen=True)
class Trade:
    symbol: str
    side: int
    note: str
    entry_time: datetime
    entry: float
    stop: float
    target: float | None
    risk: float
    exit_time: datetime
    exit_price: float
    reason: str
    gross_r: float
    cost_r: float
    breakeven_time: datetime | None
    censored: bool

    def net(self, cost_scale: float = 1.0) -> float:
        return self.gross_r - self.cost_r * cost_scale

    @property
    def usd_direction(self) -> int:
        """+1 if the trade gains when the US dollar strengthens."""
        return self.side if self.symbol.startswith("USD") else -self.side

    @property
    def hours(self) -> float:
        return (self.exit_time - self.entry_time) / HOUR


def simulate(s: Series, sig: Signal, rules: Rules, cost_pips: float, flip: bool = False) -> Trade | None:
    """One trade from the signal bar's close; ``flip`` takes the other side at the same distances."""
    i, entry = sig.index, s.c[sig.index]
    risk = (entry - sig.stop) * sig.side
    if not risk > 0 or (sig.target is not None and (sig.target - entry) * sig.side <= 0):
        return None
    sign = -sig.side if flip else sig.side
    distance = abs(sig.target - entry) if sig.target is not None else (rules.target_r * risk if rules.target_r else None)
    stop, target = entry - sign * risk, (entry + sign * distance if distance else None)
    be_level = rules.breakeven_at_r * risk if rules.breakeven_at_r is not None else 0.0
    breakeven_time: datetime | None = None

    def done(j: int, price: float, reason: str, censored: bool = False) -> Trade:
        return Trade(s.symbol, sign, sig.note, s.times[i] + HOUR, entry, entry - sign * risk, target, risk,
                     s.times[j] + HOUR, price, reason, (price - entry) * sign / risk, cost_pips * pip(s.symbol) / risk,
                     breakeven_time, censored)

    def stop_reason() -> str:
        moved = (stop - entry) * sign
        return "TRAIL" if moved > risk * 1e-9 else "BREAKEVEN" if moved > -risk * 1e-9 else "STOP"

    last = min(len(s.c), i + 1 + rules.max_hold_hours)
    for j in range(i + 1, last):
        if s.segment[j] != s.segment[i]:
            return done(j - 1, s.c[j - 1], "CENSORED", True)
        adverse, favourable = (s.l[j], s.h[j]) if sign > 0 else (s.h[j], s.l[j])
        if (s.o[j] - stop) * sign <= 0:
            return done(j, s.o[j], stop_reason())
        if (adverse - stop) * sign <= 0:
            return done(j, stop, stop_reason())
        if target is not None and (s.o[j] - target) * sign >= 0:
            return done(j, s.o[j], "TARGET")
        if target is not None and (favourable - target) * sign >= 0:
            return done(j, target, "TARGET")
        if rules.max_hours and j - i >= rules.max_hours:
            return done(j, s.c[j], "TIME")
        # The live rule, applied after the bar: break-even, then the trail, once price reached +1R.
        if (favourable - entry) * sign >= be_level:
            if rules.breakeven_at_r is not None and (entry - stop) * sign > 0:
                stop = entry
            atr = s.atr[j]
            if rules.trail_atr and atr:
                proposed = favourable - sign * rules.trail_atr * atr
                if (proposed - stop) * sign > 0:
                    stop = proposed
            if breakeven_time is None and (stop - entry) * sign >= 0:
                breakeven_time = s.times[j] + HOUR  # From here the trade counts 0 for the US-dollar cap.
    if last == len(s.c):
        return done(last - 1, s.c[last - 1], "CENSORED", True)  # Still open at the end of the data.
    return done(last - 1, s.c[last - 1], "TIME")


def portfolio(trades: Iterable[Trade], rules: Rules) -> tuple[list[Trade], Counter[str]]:
    """Apply one-trade-per-pair and the US-dollar cap in time order, as the paper bot does."""
    accepted: list[Trade] = []
    skipped: Counter[str] = Counter()
    open_trades: list[Trade] = []
    for t in sorted(trades, key=lambda t: (t.entry_time, t.symbol)):
        open_trades = [o for o in open_trades if o.exit_time > t.entry_time]
        if rules.one_trade_per_pair and any(o.symbol == t.symbol for o in open_trades):
            skipped["already in a trade on this pair"] += 1
            continue
        if rules.usd_cap_percent is not None:
            at_risk = [o for o in open_trades if o.usd_direction == t.usd_direction
                       and (o.breakeven_time is None or o.breakeven_time > t.entry_time)]
            if (len(at_risk) + 1) * rules.risk_percent > rules.usd_cap_percent + 1e-9:
                skipped["US-dollar cap"] += 1
                continue
        accepted.append(t)
        open_trades.append(t)
    return accepted, skipped


@dataclass
class Stats:
    n: int
    win_rate: float
    average: float
    margin: float      # About two standard errors of the average.
    total: float
    profit_factor: float | None
    max_drawdown: float
    losing_streak: int
    hours: float

    @classmethod
    def of(cls, trades: Sequence[Trade], cost_scale: float = 1.0) -> Stats:
        scored = sorted((t for t in trades if not t.censored), key=lambda t: t.exit_time)
        values = [t.net(cost_scale) for t in scored]
        if not values:
            return cls(0, 0.0, 0.0, 0.0, 0.0, None, 0.0, 0, 0.0)
        gains, losses = sum(v for v in values if v > 0), -sum(v for v in values if v < 0)
        peak = running = drawdown = 0.0
        streak = longest = 0
        for v in values:
            running += v
            peak = max(peak, running)
            drawdown = max(drawdown, peak - running)
            streak = streak + 1 if v < 0 else 0
            longest = max(longest, streak)
        margin = 2 * statistics.stdev(values) / sqrt(len(values)) if len(values) > 1 else 0.0
        return cls(len(values), sum(v > 0 for v in values) / len(values), statistics.fmean(values), margin,
                   sum(values), gains / losses if losses else None, drawdown, longest,
                   statistics.fmean(t.hours for t in scored))

    def line(self) -> str:
        if not self.n:
            return "no trades"
        pf = "n/a" if self.profit_factor is None else f"{self.profit_factor:.2f}"
        return (f"{self.n:,} trades, win rate {self.win_rate:.0%}, average {self.average:+.3f} R "
                f"(±{self.margin:.3f}), total {self.total:+.1f} R, profit factor {pf}")


def compound(trades: Sequence[Trade], rules: Rules) -> tuple[float, float]:
    """Balance and worst drawdown (%) at fixed-fraction risk, sized on the balance at each entry."""
    events = sorted([(t.entry_time, 1, k) for k, t in enumerate(trades) if not t.censored]
                    + [(t.exit_time, 0, k) for k, t in enumerate(trades) if not t.censored])
    balance = peak = rules.starting_balance_aud
    worst, at_risk = 0.0, dict[int, float]()
    for _, kind, k in events:
        if kind == 1:
            at_risk[k] = balance * rules.risk_percent / 100
        else:
            balance += at_risk.pop(k) * trades[k].net()
            peak = max(peak, balance)
            worst = max(worst, 1 - balance / peak if peak > 0 else 1.0)
    return balance, worst


@dataclass
class Result:
    name: str
    title: str
    description: str
    rules: Rules
    params: dict[str, Any]
    signals: int
    trades: list[Trade]
    skipped: Counter[str]
    random_averages: list[float]
    split_year: int
    min_trades: int
    checks: list[tuple[bool, str]] = field(default_factory=list)

    @property
    def stats(self) -> Stats:
        return Stats.of(self.trades)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(ok for ok, _ in self.checks)


def evaluate(result: Result) -> None:
    """The pass bar from docs/STRATEGY_WORKBENCH.md, written down before any result was seen."""
    t, split = result.trades, result.split_year
    early = Stats.of([x for x in t if x.entry_time.year < split])
    late = Stats.of([x for x in t if x.entry_time.year >= split])
    double = Stats.of(t, 2.0)
    no_jpy = Stats.of([x for x in t if x.symbol != "USDJPY"])
    overall = result.stats
    checks = [(overall.n >= result.min_trades, f"at least {result.min_trades} trades: {overall.n:,}"),
              (early.n > 0 and early.average > 0,
               f"before {split} the average is above 0: {early.average:+.3f} R over {early.n:,} trades"),
              (late.n > 0 and late.average > 0,
               f"from {split} the average is above 0: {late.average:+.3f} R over {late.n:,} trades"),
              (double.average > 0, f"at double costs the average is above 0: {double.average:+.3f} R"),
              (no_jpy.average > 0, f"without USDJPY the average is above 0: {no_jpy.average:+.3f} R")]
    if result.random_averages:
        beaten = sum(overall.average > r for r in result.random_averages) / len(result.random_averages)
        checks.append((beaten >= 0.95, ("beats random directions (same moments, stops and exits; one coin flip "
                                        f"per run of signals): better than {beaten:.0%} of "
                                        f"{len(result.random_averages)} random runs (needs 95%); random runs average "
                                        f"{statistics.fmean(result.random_averages):+.3f} R")))
    result.checks = checks


def run_strategy(name: str, history: History, settings: LabSettings, ctx: Context,
                 progress: Callable[[str], None] = print) -> Result:
    strategy = STRATEGIES[name]
    entry = settings.strategies.get(name)
    params = {**strategy.defaults, **(entry.parameters() if entry else {})}
    unknown = set(params) - set(strategy.defaults)
    if unknown:
        raise SystemExit(f"{name}: unknown setting(s) {', '.join(sorted(unknown))}; "
                         f"it takes {', '.join(strategy.defaults) or 'no settings'}.")
    rules = Rules.model_validate({**settings.rules.model_dump(), **strategy.exits, **(entry.exits if entry else {})})
    progress(f"{name}: finding signals...")
    found = strategy.find(history.series, params, ctx)
    end = datetime.combine(settings.data.end, datetime.min.time(), ctx.start.tzinfo) if settings.data.end else None
    pairs: list[tuple[Trade, Trade, int]] = []
    signals = clusters = 0
    for symbol, sigs in found.items():
        s, cost = history.series[symbol], settings.costs_pips.get(symbol)
        if cost is None:
            raise SystemExit(f"No cost for {symbol} in strategy-lab.yaml (costs_pips).")
        previous: Signal | None = None
        for sig in sorted(sigs, key=lambda x: x.index):
            at = s.times[sig.index] + HOUR
            if at <= ctx.start or (end is not None and at >= end):
                continue
            signals += 1
            # A run of same-side signals close together is one decision: the random comparison flips
            # one coin per run, keeping the strategy's clustering (a coin per signal would understate
            # how far chance alone can move a clustered strategy).
            if previous is None or sig.side != previous.side or sig.index - previous.index > CLUSTER_HOURS:
                clusters += 1
            previous = sig
            actual, flipped = simulate(s, sig, rules, cost), simulate(s, sig, rules, cost, flip=True)
            if actual is not None and flipped is not None:
                pairs.append((actual, flipped, clusters))
    progress(f"{name}: {signals:,} signals; simulating trades and {settings.random_runs} random-direction runs...")
    trades, skipped = portfolio((a for a, _, _ in pairs), rules)
    averages = []
    for run in range(settings.random_runs):
        rng = random.Random(settings.random_seed + run)
        coins = [rng.random() < 0.5 for _ in range(clusters + 1)]
        chosen, _ = portfolio([f if coins[c] else a for a, f, c in pairs], rules)
        averages.append(Stats.of(chosen).average)
    result = Result(name, strategy.title, strategy.describe(params), rules, params, signals, trades, skipped,
                    averages, settings.data.split_year, settings.min_trades)
    evaluate(result)
    return result


def _table(rows: Mapping[str, Stats]) -> list[str]:
    lines = []
    for key, st in rows.items():
        lines.append(f"  {key:<8} {st.n:>6,} trades  win {st.win_rate:>4.0%}  avg {st.average:+.3f} R  "
                     f"total {st.total:+8.1f} R" if st.n else f"  {key:<8}      0 trades")
    return lines


def report(result: Result) -> str:
    r, st, rules = result, result.stats, result.rules
    censored = sum(t.censored for t in r.trades)
    balance, drawdown = compound(r.trades, rules)
    exits = Counter(t.reason for t in r.trades if not t.censored)
    exit_text = ", ".join(f"{k.lower()} {v / st.n:.0%}" for k, v in exits.most_common()) if st.n else "none"
    rule_text = ", ".join(filter(None, [
        f"target {rules.target_r:g}R" if rules.target_r else "no fixed target",
        f"break-even at +{rules.breakeven_at_r:g}R" if rules.breakeven_at_r else "no break-even",
        f"trail {rules.trail_atr:g} x ATR" if rules.trail_atr else "no trail",
        f"time limit {rules.max_hours} h" if rules.max_hours else "",
        "one trade per pair" if rules.one_trade_per_pair else "",
        f"US-dollar cap {rules.usd_cap_percent:g}%" if rules.usd_cap_percent else ""]))
    skipped = "; ".join(f"{v:,} {k}" for k, v in r.skipped.most_common()) or "none"
    by_pair = {p: Stats.of([t for t in r.trades if t.symbol == p]) for p in sorted({t.symbol for t in r.trades})}
    by_year = {str(y): Stats.of([t for t in r.trades if t.entry_time.year == y])
               for y in sorted({t.entry_time.year for t in r.trades})}
    lines = [f"=== {r.name}: {r.title} ===", f"What it does: {r.description}",
             f"Exits and rules: {rule_text}. Risk {rules.risk_percent:g}% per trade.",
             f"Signals {r.signals:,}; traded {len(r.trades) - censored:,}; skipped: {skipped}"
             + (f"; {censored} cut off by data holes (left out)" if censored else ""),
             "",
             f"Result, net of costs: {st.line()}",
             (f"  Worst run of losses: {st.max_drawdown:.1f} R; longest losing streak {st.losing_streak}; "
              f"average time in a trade {st.hours:.0f} h"),
             f"  Exits: {exit_text}",
             (f"  A${rules.starting_balance_aud:,.0f} at {rules.risk_percent:g}% risk per trade would end at "
              f"A${balance:,.0f} (worst fall {drawdown:.0%}); illustrative, ignores lot rounding and margin."),
             "",
             "Pass bar (all must hold):"]
    lines += [f"  [{'PASS' if ok else 'FAIL'}] {text}" for ok, text in r.checks]
    lines += [f"  VERDICT: {'PASS' if r.passed else 'FAIL'}", "", "By pair:", *_table(by_pair), "By year:",
              *_table(by_year)]
    return "\n".join(lines)


def comparison(results: Sequence[Result]) -> str:
    lines = [f"{'Strategy':<13}{'Trades':>8}{'Win':>6}{'Avg R':>9}{'±':>7}{'Total R':>10}{'PF':>6}  Verdict"]
    for r in results:
        st = r.stats
        pf = "-" if st.profit_factor is None else f"{st.profit_factor:.2f}"
        lines.append(f"{r.name:<13}{st.n:>8,}{st.win_rate:>6.0%}{st.average:>+9.3f}{st.margin:>7.3f}{st.total:>+10.1f}"
                     f"{pf:>6}  {'PASS' if r.passed else 'FAIL'}")
    return "\n".join(lines)


TRADE_COLUMNS = ["symbol", "side", "note", "entry_time_utc", "entry", "stop", "target", "risk", "exit_time_utc",
                 "exit_price", "reason", "gross_r", "cost_r", "net_r", "breakeven_time_utc", "censored"]


def save(results: Sequence[Result], history: History, settings_text: str, folder: Path, ledger: Path,
         started: datetime) -> Path:
    """Write the run's summary, each strategy's trades and settings; add one ledger row per strategy."""
    folder.mkdir(parents=True, exist_ok=True)
    header = [f"STRATEGY LAB run {started:%Y-%m-%d %H:%M} (research only; nothing was traded)", history.describe(),
              "Costs: assumed round trip per trade (strategy-lab.yaml); no swap. Prices: hourly bars.", ""]
    summary = "\n".join([*header, comparison(results), "", *("\n" + report(r) for r in results), "",
                         ("How to read: a strategy is worth paper trading only with VERDICT PASS. The ± is about "
                          "two standard errors: an average within that distance of 0 may be luck.")])
    path = folder / "summary.txt"
    path.write_text(summary + "\n", encoding="utf-8")
    (folder / "settings-used.yaml").write_text(settings_text, encoding="utf-8")
    for r in results:
        with (folder / f"{r.name}-trades.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(TRADE_COLUMNS)
            for t in r.trades:
                writer.writerow([t.symbol, "BUY" if t.side > 0 else "SELL", t.note, t.entry_time.isoformat(),
                                 f"{t.entry:.5f}", f"{t.stop:.5f}", "" if t.target is None else f"{t.target:.5f}",
                                 f"{t.risk:.5f}", t.exit_time.isoformat(), f"{t.exit_price:.5f}", t.reason,
                                 f"{t.gross_r:.4f}", f"{t.cost_r:.4f}", f"{t.net():.4f}",
                                 t.breakeven_time.isoformat() if t.breakeven_time else "", int(t.censored)])
    new = not ledger.is_file()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if new:
            writer.writerow(["run", "strategy", "settings", "trades", "win_rate", "avg_r", "plus_minus", "total_r",
                             "profit_factor", "max_drawdown_r", "verdict", "folder"])
        for r in results:
            st = r.stats
            writer.writerow([f"{started:%Y-%m-%d %H:%M}", r.name, "; ".join(f"{k}={v}" for k, v in r.params.items()),
                             st.n, f"{st.win_rate:.3f}", f"{st.average:.4f}", f"{st.margin:.4f}", f"{st.total:.2f}",
                             "" if st.profit_factor is None else f"{st.profit_factor:.3f}", f"{st.max_drawdown:.2f}",
                             "PASS" if r.passed else "FAIL", str(folder)])
    return path

