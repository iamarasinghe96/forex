"""Previous day's high and low: a live scoring tool, and a study of how price behaves around them.

The idea comes from a trading video (Nasdaq futures, about 200 days in late 2024). It says price is
drawn to the previous day's high and low, where stop orders sit, and reports:
- 11% of days run neither level, 77% one, 12% both;
- after opening inside the previous day's range, a one-sided day runs its level within the morning
  session 80% of the time; after opening outside, price comes back to the level about 56% of the time;
- inside days follow two-sided days and fall on Mondays, and the day after an inside day moves more;
- after the level is run, price often reverses.

Forex trades around the clock, so here:
- a trading day runs from 17:00 to 17:00 New York time (the usual forex day; Sunday evening is Monday);
- the "open" is the London open or the New York open (08:00 local), and the "morning" is the 4 hours
  from it;
- prices are hourly bars: a level is "run" when an hour trades beyond it.

The study adds checks the video does not make. Each result is set beside the same measurement on
ordinary levels the same distance away on the other side of the open ("mirrored"); random prices give
both the same figure:
- the magnet test: how often the previous high or low is run, against its mirrored level;
- which level first: price reaches the nearer of two levels first most of the time by distance alone,
  so the previous day's levels are compared with mirrored ones;
- reversal or continuation: after the hour that first ran a level closes, does price move 1 ATR back
  or 1 ATR further first? A coin flip gives 50%.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import pairwise
from math import sqrt
from typing import Any
from zoneinfo import ZoneInfo

from forex.domain import Candle

NEW_YORK = ZoneInfo("America/New_York")
SESSIONS = (("London", ZoneInfo("Europe/London")), ("New York", NEW_YORK))
SESSION_HOUR = 8       # Local opening hour (the video uses the 9:30 New York stock open).
WINDOW_HOURS = 4       # The "morning session" after each open.
MIN_DAY_BARS = 12      # Shorter days (holidays, data gaps) are left out.
MAX_GAP_DAYS = 4       # A previous day further back than this (a data gap) is not used.
ATR_PERIOD = 14
REACTION_ATR = 1.0
REACTION_HOURS = 24
DAY_NAMES = {"inside": "inside day", "single": "single break", "double": "double break"}


def trading_date(moment: datetime) -> date:
    """The forex day a moment belongs to: each day starts at 17:00 New York."""
    return (moment.astimezone(NEW_YORK) + timedelta(hours=7)).date()


@dataclass(frozen=True)
class Day:
    date: date
    bars: tuple[Candle, ...]
    high: float
    low: float


def group_days(h1: Sequence[Candle]) -> list[Day]:
    groups: dict[date, list[Candle]] = defaultdict(list)
    for bar in h1:
        groups[trading_date(bar.timestamp_utc)].append(bar)
    days = []
    for key in sorted(groups):
        bars = tuple(sorted(groups[key], key=lambda b: b.timestamp_utc))
        days.append(Day(key, bars, max(float(b.high) for b in bars), min(float(b.low) for b in bars)))
    return days


def day_type(day: Day, previous: Day) -> str:
    """'inside' (neither previous level run), 'single' (one) or 'double' (both)."""
    return ("inside", "single", "double")[(day.high > previous.high) + (day.low < previous.low)]


def rolling_atr(bars: Sequence[Candle], period: int = ATR_PERIOD) -> dict[datetime, float]:
    """ATR at each bar's close: the mean true range of the last ``period`` bars."""
    out: dict[datetime, float] = {}
    ranges: list[float] = []
    for previous, bar in pairwise(bars):
        ranges.append(max(float(bar.high - bar.low), abs(float(bar.high - previous.close)),
                          abs(float(bar.low - previous.close))))
        if len(ranges) >= period:
            out[bar.timestamp_utc] = sum(ranges[-period:]) / period
    return out


def session_index(day: Day, zone: ZoneInfo) -> int | None:
    return next((i for i, bar in enumerate(day.bars) if bar.timestamp_utc.astimezone(zone).hour == SESSION_HOUR), None)


def first_run(bars: Sequence[Candle], high: float, low: float) -> str | None:
    """Which level an hour traded beyond first: 'high', 'low', 'both' (the same hour) or None."""
    for bar in bars:
        up, down = float(bar.high) > high, float(bar.low) < low
        if up or down:
            return "both" if up and down else "high" if up else "low"
    return None


def _session(c: dict[str, float], name: str, zone: ZoneInfo, day: Day, previous: Day, kind: str) -> None:
    start = session_index(day, zone)
    if start is None:
        return
    rest = day.bars[start:]
    end = rest[0].timestamp_utc + timedelta(hours=WINDOW_HOURS)
    window = [b for b in rest if b.timestamp_utc < end]
    open_, high, low = float(rest[0].open), previous.high, previous.low
    w_high, w_low = max(float(b.high) for b in window), min(float(b.low) for b in window)
    p = name + ":"
    c[p + "opens"] += 1
    if low <= open_ <= high:
        c[p + "inside"] += 1
        c[p + "inside_ran"] += w_high > high or w_low < low
        if kind == "single":
            c[p + "single"] += 1
            c[p + "single_ran"] += (w_high > high) if day.high > high else (w_low < low)
        up, down = high - open_, open_ - low
        nearer = "high" if up < down else "low"
        # Mirror: the same two distances on the other sides, so its nearer level is the other way.
        for key, first in (("", first_run(rest, high, low)), ("mirror_", first_run(rest, open_ + down, open_ - up))):
            if first in {"high", "low"}:
                c[p + key + "decided"] += 1
                c[p + key + "nearer_first"] += first == (nearer if not key else "low" if nearer == "high" else "high")
        c[p + "magnet_n"] += 2
        c[p + "magnet_real"] += (w_high > high) + (w_low < low)
        c[p + "magnet_mirror"] += (w_low < open_ - up) + (w_high > open_ + down)
    else:
        above = open_ > high
        level = high if above else low
        distance = abs(open_ - level)
        c[p + "outside"] += 1
        c[p + "outside_back_window"] += (w_low <= level) if above else (w_high >= level)
        c[p + "outside_back_day"] += (min(float(b.low) for b in rest) <= level if above
                                      else max(float(b.high) for b in rest) >= level)
        c[p + "outside_mirror"] += (w_high >= open_ + distance) if above else (w_low <= open_ - distance)


def _reaction(c: dict[str, float], day: Day, previous: Day, bars: Sequence[Candle],
              position: Mapping[datetime, int], atrs: Mapping[datetime, float]) -> None:
    for side, level in (("high", previous.high), ("low", previous.low)):
        hit = next((b for b in day.bars if (float(b.high) > level if side == "high" else float(b.low) < level)), None)
        if hit is None or hit.timestamp_utc not in atrs:
            continue
        close, size = float(hit.close), atrs[hit.timestamp_utc] * REACTION_ATR
        swept = close <= level if side == "high" else close >= level
        outcome = "neither"
        start = position[hit.timestamp_utc] + 1
        for later in bars[start:start + REACTION_HOURS]:
            down, up = float(later.low) <= close - size, float(later.high) >= close + size
            back, further = (down, up) if side == "high" else (up, down)
            if back or further:
                outcome = "same_hour" if back and further else "back" if back else "further"
                break
        c[f"reaction_{'swept' if swept else 'beyond'}_{outcome}"] += 1


def measure(h1: Sequence[Candle]) -> dict[str, float]:
    """Counts for one pair; counts from several pairs add up to the pooled result."""
    c: dict[str, float] = defaultdict(float)
    bars = sorted({b.timestamp_utc: b for b in h1}.values(), key=lambda b: b.timestamp_utc)
    position = {b.timestamp_utc: i for i, b in enumerate(bars)}
    atrs = rolling_atr(bars)
    days = [d for d in group_days(bars) if len(d.bars) >= MIN_DAY_BARS]
    ranges: list[float] = []
    previous_type: str | None = None
    for previous, day in pairwise(days):
        ranges.append(previous.high - previous.low)
        if (day.date - previous.date).days > MAX_GAP_DAYS:
            previous_type = None
            continue
        kind = day_type(day, previous)
        c["days"] += 1
        c[kind] += 1
        weekday = "monday" if day.date.weekday() == 0 else "other_weekday"
        c[weekday] += 1
        c[weekday + "_inside"] += kind == "inside"
        if previous_type == "double":
            c["after_double"] += 1
            c["after_double_inside"] += kind == "inside"
        if len(ranges) >= 20 and previous_type is not None:
            group = "after_inside" if previous_type == "inside" else "after_other"
            c[group] += 1
            c[group + "_ratio"] += (day.high - day.low) / (sum(ranges[-20:]) / 20)
        previous_type = kind
        for name, zone in SESSIONS:
            _session(c, name, zone, day, previous, kind)
        _reaction(c, day, previous, bars, position, atrs)
    return c


def share(k: float, n: float) -> str:
    """'62% of 512 (±4%)': the ± is about two standard errors, the range chance alone could move it."""
    if not n:
        return "no cases"
    p = k / n
    return f"{p:.0%} of {n:.0f} (±{2 * sqrt(p * (1 - p) / n):.0%})"


def section(c: Mapping[str, float], label: str) -> list[str]:
    def g(key: str) -> float:
        return c.get(key, 0.0)

    lines = [f"== {label} ==",
             "1. What kind of day (video, Nasdaq: neither 11%, one side 77%, both 12%)",
             f"  Neither level run (inside day): {share(g('inside'), g('days'))}",
             f"  One side run (single break): {share(g('single'), g('days'))}",
             f"  Both sides run (double break): {share(g('double'), g('days'))}",
             (f"  Inside days on Mondays: {share(g('monday_inside'), g('monday'))}; on other days: "
              f"{share(g('other_weekday_inside'), g('other_weekday'))}"),
             f"  Inside days right after a double break: {share(g('after_double_inside'), g('after_double'))}"]
    if g("after_inside") and g("after_other"):
        lines.append(f"  Range of the day after an inside day: {g('after_inside_ratio') / g('after_inside'):.2f} x the "
                     f"20-day average ({g('after_inside'):.0f} days); after other days "
                     f"{g('after_other_ratio') / g('after_other'):.2f} x")
    for number, (name, _) in enumerate(SESSIONS, start=2):
        p = name + ":"
        lines += [f"{number}. From the {name} open (08:00 {name} time), next {WINDOW_HOURS} hours",
                  f"  Opened inside the previous day's range: {share(g(p + 'inside'), g(p + 'opens'))}",
                  "  Opening inside:",
                  ("  - the video's 80% (only days that turned out single-break): the level was run in time on "
                   f"{share(g(p + 'single_ran'), g(p + 'single'))}"),
                  ("  - every day opening inside (all that is known at the open): a level was run in time on "
                   f"{share(g(p + 'inside_ran'), g(p + 'inside'))}"),
                  (f"  - the nearer level was run first on {share(g(p + 'nearer_first'), g(p + 'decided'))}; "
                   "mirrored levels (same distances, other sides) on "
                   f"{share(g(p + 'mirror_nearer_first'), g(p + 'mirror_decided'))}"),
                  ("  - magnet test, in time: the previous high or low was run on "
                   f"{share(g(p + 'magnet_real'), g(p + 'magnet_n'))}; a level the same distance the other way on "
                   f"{share(g(p + 'magnet_mirror'), g(p + 'magnet_n'))}"),
                  "  Opening outside (above the high or below the low):",
                  (f"  - came back to the level in time on {share(g(p + 'outside_back_window'), g(p + 'outside'))}; "
                   f"by the day's end on {share(g(p + 'outside_back_day'), g(p + 'outside'))} (video: about 56%)"),
                  f"  - moved the same distance away in time on {share(g(p + 'outside_mirror'), g(p + 'outside'))}"]
    lines.append(f"{len(SESSIONS) + 2}. After the hour that first ran the previous high or low closed: did price move "
                 f"{REACTION_ATR:g} ATR back or {REACTION_ATR:g} ATR further first? (a coin flip gives 50%)")
    for group, words in (("swept", "the hour closed back inside the range (a sweep)"),
                         ("beyond", "the hour closed beyond the level")):
        back, further = g(f"reaction_{group}_back"), g(f"reaction_{group}_further")
        lines.append(f"  - {words}: back first on {share(back, back + further)}; "
                     f"{g(f'reaction_{group}_same_hour'):.0f} both in one hour, "
                     f"{g(f'reaction_{group}_neither'):.0f} neither within {REACTION_HOURS} hours")
    return lines


HOW_TO_READ = """How to read this:
- The ± after each figure is about two standard errors: a difference smaller than that can be chance.
- A level being reached often is not an edge by itself: random prices reach levels too. An edge shows
  only where the previous high/low beats its mirrored level (same distance, other side), or "back
  first" differs from 50%, by more than the ± ranges.
- On computer-made random prices this study gives about 11% inside, 79% single and 10% double-break
  days, close to the video's 11/77/12: that split is what chance produces.
- The 80% in the video counts only days that turned out one-sided, which is known only at the day's
  end. The "every day opening inside" line is what can be traded.
- Hourly bars hide the order of moves inside an hour; costs (about 1 pip) are not included."""


def levels_report(by_symbol: Mapping[str, Sequence[Candle]]) -> tuple[str, str]:
    """(short summary for Telegram, full report with each pair) from stored hourly prices."""
    counts = {s.upper(): measure(bars) for s, bars in by_symbol.items() if bars}
    if not counts or not sum(c.get("days", 0.0) for c in counts.values()):
        text = "Not enough stored hourly prices yet for the previous-day study."
        return text, text
    pooled: dict[str, float] = defaultdict(float)
    for c in counts.values():
        for key, value in c.items():
            pooled[key] += value
    stamps = [b.timestamp_utc for bars in by_symbol.values() for b in bars]
    header = [(f"PREVIOUS DAY'S HIGH AND LOW: {', '.join(counts)}, hourly prices {min(stamps):%d %b %Y} to "
               f"{max(stamps):%d %b %Y} ({pooled['days']:.0f} trading days in all)."),
              "A forex day runs 17:00 to 17:00 New York time. A level is 'run' when an hour trades beyond it.", ""]
    summary = "\n".join(header + section(pooled, "All pairs together"))
    full = [*header, *section(pooled, "All pairs together")]
    for symbol, c in counts.items():
        full += ["", *section(c, symbol)]
    return summary, "\n".join([*full, "", HOW_TO_READ])


def levels_now(h1: Sequence[Candle], now: datetime, atr_value: float) -> dict[str, Any] | None:
    """Live readings for the scorecard: the previous day's levels, and what today has done so far."""
    days = group_days(h1[-24 * 7:])
    today = days[-1] if days and days[-1].date == trading_date(now) else None
    done = [d for d in days if d is not today and len(d.bars) >= MIN_DAY_BARS]
    if not done:
        return None
    previous, close = done[-1], float(h1[-1].close)
    before = done[-2] if len(done) > 1 and (previous.date - done[-2].date).days <= MAX_GAP_DAYS else None
    result: dict[str, Any] = {
        "date": previous.date.isoformat(), "high": round(previous.high, 5), "low": round(previous.low, 5),
        "type": day_type(previous, before) if before else None,
        "to_high_atr": round((previous.high - close) / atr_value, 2) if atr_value else None,
        "to_low_atr": round((close - previous.low) / atr_value, 2) if atr_value else None,
        "today": None}
    if today is not None:
        opens = {}
        for name, zone in SESSIONS:
            index = session_index(today, zone)
            if index is not None:
                x = float(today.bars[index].open)
                opens[name] = "inside" if previous.low <= x <= previous.high else "above" if x > previous.high else "below"
        result["today"] = {"ran_high": today.high > previous.high, "ran_low": today.low < previous.low, "opens": opens}
    return result


def levels_text(levels: Mapping[str, Any]) -> str:
    """One scorecard line, e.g. 'Previous day (single break): high 1.09120, 0.8 ATR above price; ...'."""
    def away(distance: Any, positive: str, negative: str) -> str:
        return "" if distance is None else f", {abs(distance):.1f} ATR {positive if distance >= 0 else negative} price"

    kind = f" ({DAY_NAMES[levels['type']]})" if levels.get("type") else ""
    text = (f"Previous day{kind}: high {levels['high']}{away(levels.get('to_high_atr'), 'above', 'below')}; "
            f"low {levels['low']}{away(levels.get('to_low_atr'), 'below', 'above')}.")
    today = levels.get("today")
    if today:
        ran = [word for word, flag in (("the high", today["ran_high"]), ("the low", today["ran_low"])) if flag]
        where = {"inside": "inside the range", "above": "above the high", "below": "below the low"}
        opens = "; ".join(f"{name} opened {where[pos]}" for name, pos in today["opens"].items())
        text += f" Today so far: ran {' and '.join(ran) or 'neither'}" + (f"; {opens}." if opens else ".")
    return text
