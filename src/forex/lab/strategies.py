"""Strategies the lab can test. Each finds entry signals on one pair's hourly history.

A signal is decided at the close of an hourly bar, using only that bar and earlier ones, and the
trade enters at that close. It carries a stop and, optionally, its own target; exits otherwise
follow the paper bot's rules (``strategy-lab.yaml``, ``rules``).

To add a strategy: write a ``find`` function, register it in ``STRATEGIES`` with its default
parameters, and give it a section in ``strategy-lab.yaml``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import Any

from forex.day_levels import (
    MAX_GAP_DAYS,
    MIN_DAY_BARS,
    SESSIONS,
    WINDOW_HOURS,
    Day,
    group_days,
    session_index,
)
from forex.lab.data import Series

LOGGER = logging.getLogger("forex.lab")


@dataclass(frozen=True)
class Signal:
    index: int                  # The signal bar; the trade enters at its close.
    side: int                   # +1 buy, -1 sell.
    stop: float
    target: float | None = None  # None: the rules' target (target_r).
    note: str = ""


@dataclass
class Context:
    analysis_json: str = ""       # config.yaml's analysis section, for trend-v1.
    cache: Path = Path("data/lab-cache")
    workers: int = 1
    start: datetime = datetime(2012, 4, 1, tzinfo=UTC)


Finder = Callable[[dict[str, Series], Mapping[str, Any], Context], dict[str, list[Signal]]]


@dataclass(frozen=True)
class Strategy:
    name: str
    title: str
    describe: Callable[[Mapping[str, Any]], str]
    find: Finder
    defaults: dict[str, Any] = field(default_factory=dict)
    exits: dict[str, Any] = field(default_factory=dict)   # Rule overrides that belong to the idea.


def each_pair(find: Callable[[Series, Mapping[str, Any]], list[Signal]]) -> Finder:
    def run(series: dict[str, Series], params: Mapping[str, Any], _: Context) -> dict[str, list[Signal]]:
        return {symbol: find(s, params) for symbol, s in series.items()}
    return run


# ---- Previous day's high and low (forex day 17:00-17:00 New York; see forex.day_levels) ----

def day_frames(s: Series) -> Iterator[tuple[Day, Day, list[int]]]:
    """Each full day with its previous full day, as bar indexes into the series."""
    days = [d for d in group_days(s.bars) if len(d.bars) >= MIN_DAY_BARS]
    for previous, day in pairwise(days):
        indexes = [s.index[b.timestamp_utc] for b in day.bars]
        if ((day.date - previous.date).days <= MAX_GAP_DAYS
                and s.segment[indexes[0]] == s.segment[s.index[previous.bars[-1].timestamp_utc]]):
            yield day, previous, indexes


def in_sessions(moment: datetime, sessions: Any) -> bool:
    """True for 'any', or when the hour starts inside one of the named sessions' first hours."""
    if sessions in (None, "any"):
        return True
    for name, zone in SESSIONS:
        if name in sessions and 8 <= moment.astimezone(zone).hour < 8 + WINDOW_HOURS:
            return True
    return False


def find_sweep(s: Series, p: Mapping[str, Any]) -> list[Signal]:
    out = []
    for _, previous, indexes in day_frames(s):
        done: set[str] = set()
        for i in indexes:
            for name, level, sign in (("high", previous.high, -1), ("low", previous.low, 1)):
                ran = s.h[i] > level if name == "high" else s.l[i] < level
                if name in done or not ran:
                    continue
                done.add(name)  # Only the first hour that runs each level.
                atr = s.atr[i]
                swept = s.c[i] <= level if name == "high" else s.c[i] >= level
                if (atr is None or not swept or (s.h[i] > previous.high and s.l[i] < previous.low)
                        or not in_sessions(s.times[i], p["sessions"])):
                    continue
                stop = s.h[i] + p["buffer_atr"] * atr if sign < 0 else s.l[i] - p["buffer_atr"] * atr
                risk = (s.c[i] - stop) * sign
                if not p["min_stop_atr"] * atr <= risk <= p["max_stop_atr"] * atr:
                    continue
                target = (previous.low if sign < 0 else previous.high) if p["target"] == "opposite" else None
                out.append(Signal(i, sign, stop, target, f"swept the previous day's {name}"))
    return out


def find_breakout(s: Series, p: Mapping[str, Any]) -> list[Signal]:
    out = []
    for _, previous, indexes in day_frames(s):
        done: set[str] = set()
        for i in indexes:
            atr = s.atr[i]
            for name, sign in (("high", 1), ("low", -1)):
                beyond = s.c[i] > previous.high if name == "high" else s.c[i] < previous.low
                if name in done or not beyond:
                    continue
                done.add(name)  # Only the first hour that closes beyond each level.
                if atr is None or not in_sessions(s.times[i], p["sessions"]):
                    continue
                out.append(Signal(i, sign, s.c[i] - sign * p["stop_atr"] * atr, None,
                                  f"closed beyond the previous day's {name}"))
    return out


def find_magnet(s: Series, p: Mapping[str, Any]) -> list[Signal]:
    out = []
    for day, previous, indexes in day_frames(s):
        for name, zone in SESSIONS:
            if name not in p["sessions"]:
                continue
            k = session_index(day, zone)
            if not k:
                continue
            i = indexes[k - 1]  # The hour before the open; its close is the opening price.
            x, atr = s.c[i], s.atr[i]
            if atr is None or not previous.low <= x <= previous.high:
                continue
            up, down = previous.high - x, x - previous.low
            sign, distance, level = (1, up, previous.high) if up < down else (-1, down, previous.low)
            if not p["min_atr"] * atr <= distance <= p["max_atr"] * atr:
                continue
            out.append(Signal(i, sign, x - sign * distance * p["stop_ratio"], level,
                              f"{name} open inside; towards the previous day's {'high' if sign > 0 else 'low'}"))
    return out


# ---- The old trend strategy (trend-v1), replayed hour by hour with the live analysis code ----

def trend_job(job: tuple[str, list[Any], list[tuple[int, int]], str, str]) -> list[tuple[int, int, float]]:
    from forex.analysis import InsufficientDataError, Side, analyse_market, prepare_candles
    from forex.config import AnalysisConfig
    from forex.history import aggregate_h4

    symbol, bars, ranges, analysis_json, start_iso = job
    config, start = AnalysisConfig.model_validate_json(analysis_json), datetime.fromisoformat(start_iso)
    found: list[tuple[int, int, float]] = []
    for first, last in ranges:
        h1 = bars[first:last]
        if h1[-1].timestamp_utc < start:
            continue
        p1, p4 = prepare_candles(h1, config), prepare_candles(aggregate_h4(h1, 0), config)
        print(f"  trend-v1 {symbol}: replaying {h1[0].timestamp_utc:%Y-%m} to {h1[-1].timestamp_utc:%Y-%m} "
              f"({len(h1):,} hours)", flush=True)
        for k, candle in enumerate(h1):
            now = candle.timestamp_utc + timedelta(hours=1)
            if now <= start:
                continue
            try:
                candidate = analyse_market(symbol, p1, p4, now, config).candidate
            except InsufficientDataError:
                continue
            if candidate is not None:
                side = 1 if candidate.side is Side.LONG else -1
                levels = candidate.structural_reference_levels
                found.append((first + k, side, float(levels["rolling_low" if side > 0 else "rolling_high"])))
    return found


def find_trend(series: dict[str, Series], _: Mapping[str, Any], ctx: Context) -> dict[str, list[Signal]]:
    """The old strategy's signals, cached per pair, data and analysis settings (the replay is slow)."""
    ctx.cache.mkdir(parents=True, exist_ok=True)
    out: dict[str, list[Signal]] = {}
    jobs, files = [], {}
    for symbol, s in series.items():
        key = sha256(f"trend-v1-cache-1|{s.fingerprint()}|{ctx.analysis_json}|{ctx.start}".encode()).hexdigest()[:16]
        files[symbol] = ctx.cache / f"trend-v1-{symbol}-{key}.json"
        if files[symbol].is_file():
            rows = json.loads(files[symbol].read_text(encoding="utf-8"))
            out[symbol] = [Signal(s.index[datetime.fromisoformat(t)], side, stop, None, "old trend setup")
                           for t, side, stop in rows]
        else:
            jobs.append((symbol, s.bars, s.segment_ranges(), ctx.analysis_json, ctx.start.isoformat()))
    if jobs:
        print(f"trend-v1: replaying the old strategy hour by hour for {', '.join(j[0] for j in jobs)}. This takes "
              "10-30 minutes the first time; the result is saved and reused.", flush=True)
        if ctx.workers > 1 and len(jobs) > 1:
            with ProcessPoolExecutor(max_workers=min(ctx.workers, len(jobs))) as pool:
                results = list(pool.map(trend_job, jobs))
        else:
            results = [trend_job(job) for job in jobs]
        for job, found in zip(jobs, results, strict=True):
            symbol, s = job[0], series[job[0]]
            files[symbol].write_text(json.dumps([[s.times[i].isoformat(), side, stop] for i, side, stop in found]),
                                     encoding="utf-8")
            out[symbol] = [Signal(i, side, stop, None, "old trend setup") for i, side, stop in found]
    return out


def _sessions_text(p: Mapping[str, Any]) -> str:
    sessions: list[str] | str | None = p.get("sessions")
    if sessions is None or isinstance(sessions, str):
        return "any time of day"
    return f"the first {WINDOW_HOURS} hours of " + " or ".join(str(x) for x in sessions)


STRATEGIES: dict[str, Strategy] = {s.name: s for s in (
    Strategy("trend-v1", "Old trend strategy (reference)",
             lambda p: ("The strategy the paper bot traded until 17 Oct: 4-hour trend, 1-hour setup score at least "
                        "0.45, stop at the 20-hour low/high (analysis settings from config.yaml)."),
             find_trend),
    Strategy("pd-sweep", "Previous-day sweep reversal",
             lambda p: (f"The first hour of the day that trades beyond the previous day's high but closes back below "
                        f"it: sell (mirrored for the low: buy), during {_sessions_text(p)}. Stop {p['buffer_atr']} ATR "
                        f"beyond that hour's extreme, {p['min_stop_atr']}-{p['max_stop_atr']} ATR from entry. Target: "
                        + ("the opposite previous-day level." if p["target"] == "opposite" else "the rules' target.")),
             each_pair(find_sweep),
             {"sessions": "any", "buffer_atr": 0.1, "min_stop_atr": 0.3, "max_stop_atr": 3.0, "target": "rules"}),
    Strategy("pd-breakout", "Previous-day breakout",
             lambda p: (f"The first hour of the day that closes beyond the previous day's high: buy (beyond the low: "
                        f"sell), during {_sessions_text(p)}. Stop {p['stop_atr']} ATR from entry."),
             each_pair(find_breakout), {"sessions": "any", "stop_atr": 1.0}),
    Strategy("pd-magnet", "Previous-day magnet",
             lambda p: (f"At the {' and '.join(p['sessions'])} open (08:00 local), when price is inside the previous "
                        f"day's range: trade towards the nearer of its high and low, if it is {p['min_atr']}-"
                        f"{p['max_atr']} ATR away. Target that level; stop {p['stop_ratio']} x that distance the other "
                        "way."),
             each_pair(find_magnet),
             {"sessions": ["London", "New York"], "min_atr": 0.5, "max_atr": 3.0, "stop_ratio": 1.0},
             {"breakeven_at_r": None, "trail_atr": None, "max_hours": WINDOW_HOURS}),
)}
