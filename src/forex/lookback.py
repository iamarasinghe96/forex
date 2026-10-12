"""A self-contained ChatGPT prompt reviewing every recent trade (``/lookback`` in Telegram).

The operator wants a regular look back at what went right and wrong across trades, reviewed by
ChatGPT, which cannot see this repository. Like the loss prompt (loss_review.py), this carries the
instructions, the research so far and the bot's rules generated from the live settings. It adds:
- results at a glance, with the range the research expectation allows for this many trades;
- breakdowns by pair, direction, session, exit, trend strength, entry location and stop width;
- winners against losers, on the bot's own entry measurements;
- trades that were open at the same time;
- one row per trade, and for the latest trades the bot's reasons and a 4-hour price path;
- the trades open now and the market clock for the period.

It reads only the bot's own records and sends nothing anywhere.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import fmean
from typing import Any
from zoneinfo import ZoneInfo

from forex.config import AppConfig
from forex.domain import Candle
from forex.journal import JournalEvent, JournalStore
from forex.loss_review import (
    MARKET_EVENTS,
    _d,
    _duration,
    _f,
    _price,
    _side,
    clock_line,
    pip_size,
    research_text,
    strategy_lines,
)

PROMPT_VERSION = "lookback-chatgpt-v1"
INSTRUCTIONS_FILE = Path(__file__).parent / "prompts" / "lookback-review-chatgpt-v1.md"
DEFAULT_DAYS, MAX_DAYS = 14, 90
MAX_DETAILED = 20                       # Latest trades with full details; older ones keep their table row.
HOUR = timedelta(hours=1)
EXPECTED_R = (0.02, 0.06)               # Research expectation per trade (see research-so-far.md).
R_SPREAD = 1.06                         # Per-trade results vary by about 1.06 R (13-year audit).
BREAK_EVEN_R = 0.1                      # |R| below this counts as break-even (stop moved to entry).


@dataclass(frozen=True)
class Trade:
    trade_id: str
    symbol: str
    side: str
    opened: datetime
    closed: datetime | None              # None while the trade is open.
    entry: Decimal
    first_stop: Decimal
    last: Decimal | None                 # Exit price, or the latest price of an open trade.
    current_stop: Decimal | None
    target: Decimal | None
    volume: str
    exit_reason: str                     # STOP, TARGET, FLATTEN or OPEN.
    pnl: Decimal | None                  # Realised, or open P&L while open.
    balance: Decimal | None              # Balance after a closed trade.
    candidate: Mapping[str, Any]
    review: Mapping[str, Any]
    spread_pips: float | None

    @property
    def sign(self) -> int:
        return 1 if self.side == "LONG" else -1

    @property
    def risk(self) -> Decimal:
        return abs(self.entry - self.first_stop)

    def r_at(self, price: Decimal) -> float | None:
        return None if self.risk == 0 else float((price - self.entry) * self.sign / self.risk)

    @property
    def r(self) -> float | None:
        return None if self.last is None else self.r_at(self.last)

    def feature(self, name: str) -> float | None:
        return _f((self.candidate.get("feature_snapshot") or {}).get(name))

    @property
    def atr(self) -> Decimal | None:
        value = _d((self.candidate.get("feature_snapshot") or {}).get("h1_atr"))
        return value if value else None

    @property
    def extreme(self) -> float | None:
        """Range position in the trade's direction: 1 = bought at the 20-hour high or sold at the low."""
        position = self.feature("h1_range_position")
        return None if position is None else (position if self.sign > 0 else 1 - position)

    @property
    def ema_distance(self) -> float | None:
        distance = self.feature("h1_distance_fast_atr")
        return None if distance is None else distance * self.sign

    @property
    def stop_atr(self) -> float | None:
        return None if self.atr is None else float(self.risk / self.atr)

    @property
    def trend(self) -> float | None:
        return _f((self.candidate.get("h4_regime") or {}).get("trend_strength"))

    def component(self, name: str) -> float | None:
        return _f((self.candidate.get("setup_strength_components") or {}).get(name))

    @property
    def sessions(self) -> tuple[str, ...]:
        return tuple(self.candidate.get("session_context") or ("UNKNOWN",))

    @property
    def outcome(self) -> str:
        if self.closed is None:
            return "open"
        r = self.r
        if r is None:
            return "unknown"
        return "win" if r >= BREAK_EVEN_R else "loss" if r <= -BREAK_EVEN_R else "break-even"

    @property
    def label(self) -> str:
        return f"{self.symbol} {_side(self.side)}"


def _plain(symbol: Any) -> str:
    return str(symbol or "?").upper().split(".")[0]


def _spread(journal: JournalStore, intent: Mapping[str, Any]) -> float | None:
    execution = journal.find("PAPER", "execution", str(intent.get("candidate_id", ""))) if intent else None
    return _f(execution.payload.get("entry_spread_pips")) if execution is not None else None


def _trade(journal: JournalStore, event: JournalEvent, opened_event: JournalEvent | None,
           live: Mapping[str, Any] | None) -> Trade | None:
    p = event.payload
    provenance: Mapping[str, Any] = (p["decision_provenance"] if isinstance(p.get("decision_provenance"), Mapping)
                                     else {})
    candidate: Mapping[str, Any] = (provenance.get("candidate") or {}).get("candidate") or {}
    intent: Mapping[str, Any] = p["intent"] if isinstance(p.get("intent"), Mapping) else {}
    position: Mapping[str, Any] = p["position"] if isinstance(p.get("position"), Mapping) else p
    closed = event.kind == "trade_closed"
    first_stop = _d(intent.get("stop")) or _d((opened_event.payload if opened_event else {}).get("stop"))
    if not closed:
        first_stop = first_stop or _d(p.get("stop"))
    entry = _d(p.get("entry")) or _d(position.get("entry"))
    if entry is None or first_stop is None:
        return None
    side = str(candidate.get("side") or intent.get("side") or p.get("direction") or position.get("side"))
    opened = datetime.fromisoformat(str(p.get("opened_at_utc"))) if closed else event.observed_at_utc
    quote: Mapping[str, Any] = live or {}
    return Trade(
        event.entity_id, _plain(candidate.get("symbol") or p.get("symbol")), side, opened,
        event.observed_at_utc if closed else None, entry, first_stop,
        _d(p.get("exit")) if closed else _d(quote.get("market_price")),
        _d(position.get("stop")) if closed else _d(quote.get("stop")) or _d(p.get("stop")),
        _d(position.get("target")), str(p.get("volume") or position.get("volume") or "?"),
        str(p.get("reason", "?")) if closed else "OPEN",
        _d(p.get("pnl_aud")) if closed else _d(quote.get("unrealized_pnl_aud")),
        _d(p.get("balance")) if closed else None, candidate,
        (provenance.get("context_review") or {}).get("review") or {}, _spread(journal, intent))


def load_trades(journal: JournalStore, since: datetime) -> tuple[list[Trade], list[Trade], list[Trade]]:
    """(closed in the period, open now, every closed trade for the balance history), oldest first."""
    closed_events = journal.of_kind("PAPER", "trade_closed", limit=100_000)
    opened = {e.entity_id: e for e in journal.of_kind("PAPER", "trade_opened", limit=100_000)}
    health = journal.of_kind("PAPER", "health", limit=1)
    live = {str(item.get("client_id")): item for item in (health[-1].payload.get("positions") or [])} if health else {}
    everything = [t for e in closed_events if (t := _trade(journal, e, opened.get(e.entity_id), None))]
    closed_ids = {e.entity_id for e in closed_events}
    still_open = [t for e in opened.values() if e.entity_id not in closed_ids
                  if (t := _trade(journal, e, None, live.get(e.entity_id)))]
    return ([t for t in everything if t.closed and t.closed >= since], sorted(still_open, key=lambda t: t.opened),
            everything)


@dataclass(frozen=True)
class Excursion:
    best: float | None
    best_after_hours: float | None
    worst: float | None
    prior_move_atr: float | None
    after_best: float | None
    after_worst: float | None
    after_hours: int


def excursion(trade: Trade, candles: Sequence[Candle], now: datetime) -> Excursion:
    """Excursions in R from the stored hourly bars (hourly highs/lows: approximate)."""
    end = trade.closed or now
    ordered = sorted(candles, key=lambda c: c.timestamp_utc)
    during = [c for c in ordered if c.timestamp_utc + HOUR > trade.opened and c.timestamp_utc <= end]
    before = [c for c in ordered if c.timestamp_utc + HOUR <= trade.opened][-24:]
    after = [c for c in ordered if trade.closed and c.timestamp_utc > trade.closed][:24]

    def best_of(c: Candle) -> float | None:
        return trade.r_at(c.high if trade.sign > 0 else c.low)

    def worst_of(c: Candle) -> float | None:
        return trade.r_at(c.low if trade.sign > 0 else c.high)

    best_bar = max(during, key=lambda c: v if (v := best_of(c)) is not None else -math.inf, default=None)
    prior = None
    if before and trade.atr:
        prior = float((before[-1].close - before[0].open) * trade.sign / trade.atr)
    after_best = [v for c in after if (v := best_of(c)) is not None]
    after_worst = [v for c in after if (v := worst_of(c)) is not None]
    worst_values = [v for c in during if (v := worst_of(c)) is not None]
    return Excursion(
        best_of(best_bar) if best_bar else None,
        max(0.0, (best_bar.timestamp_utc - trade.opened).total_seconds() / 3600) if best_bar else None,
        min(worst_values) if worst_values else None, prior,
        max(after_best) if after_best else None, min(after_worst) if after_worst else None, len(after))


def _num(value: float | None, fmt: str = "+.2f") -> str:
    return "–" if value is None else format(value, fmt)


def _money(value: Decimal | None) -> str:
    return "–" if value is None else f"A${value:+,.2f}"


def _held(trade: Trade, now: datetime) -> str:
    return _duration((trade.closed or now) - trade.opened)


def results_lines(closed: Sequence[Trade], open_now: Sequence[Trade], everything: Sequence[Trade],
                  config: AppConfig, journal: JournalStore) -> list[str]:
    rs = [t.r for t in closed if t.r is not None]
    if not closed or not rs:
        return ["- No trades closed in this period."]
    pnls = [t.pnl for t in closed if t.pnl is not None]
    wins = [t for t in closed if t.outcome == "win"]
    losses = [t for t in closed if t.outcome == "loss"]
    even = [t for t in closed if t.outcome == "break-even"]
    gains = sum((p for p in pnls if p > 0), Decimal(0))
    drops = -sum((p for p in pnls if p < 0), Decimal(0))
    first = closed[0]
    start = (first.balance - first.pnl) if first.balance is not None and first.pnl is not None else None
    balance = journal.of_kind("PAPER", "balance", limit=1)
    now_balance = _d(balance[-1].payload.get("balance")) if balance else closed[-1].balance
    now_equity = _d(balance[-1].payload.get("equity")) if balance else None
    n = len(rs)
    low, high = EXPECTED_R[0] - 2 * R_SPREAD / math.sqrt(n), EXPECTED_R[1] + 2 * R_SPREAD / math.sqrt(n)
    average = fmean(rs) if rs else None
    lines = [
        (f"- **Closed trades:** {len(closed)} ({len(wins)} won, {len(losses)} lost, {len(even)} about break-even, "
        f"i.e. within ±{BREAK_EVEN_R} R). Open now: {len(open_now)}."),
        f"- **Total:** {sum(rs):+.2f} R, {_money(sum(pnls, Decimal(0)))}."
        + (f" Balance A${start:,.2f} at the start of the period → A${now_balance:,.2f} now"
           f" ({(now_balance - start) / start * 100:+.1f}%)." if start and now_balance else "")
        + (f" Equity including open trades: A${now_equity:,.2f}." if now_equity is not None else ""),
        (f"- **Average per trade:** {_num(average)} R. Win rate {len(wins) / len(closed) * 100:.0f}%."
        f" Average win {_num(fmean([t.r for t in wins if t.r is not None]) if wins else None)} R;"
        f" average loss {_num(fmean([t.r for t in losses if t.r is not None]) if losses else None)} R."),
        f"- **Largest win** {_num(max(rs))} R; **largest loss** {_num(min(rs))} R. Profit factor (A$ won ÷ A$ lost): "
        + (f"{gains / drops:.2f}." if drops else "n/a (no losses)."),
        f"- **Expected range:** the research expects +{EXPECTED_R[0]:.2f} to +{EXPECTED_R[1]:.2f} R per trade, and "
        f"single trades vary by about {R_SPREAD} R. So over {n} trades the average would normally land between "
        f"{low:+.2f} and {high:+.2f} R (two standard errors). The average so far, {_num(average)} R, is "
        + ("**inside** that range: this sample cannot yet show the strategy is better or worse than expected."
           if average is not None and low <= average <= high else
           "**outside** that range: worth investigating, though the sample is still small."),
    ]
    lines += drawdown_lines(everything, config)
    return lines


def drawdown_lines(everything: Sequence[Trade], config: AppConfig) -> list[str]:
    peak = Decimal(str(config.paper.starting_balance_aud))
    worst, at, streak, longest = Decimal(0), "", 0, 0
    for trade in everything:
        if trade.balance is not None:
            peak = max(peak, trade.balance)
            if peak > 0 and (peak - trade.balance) / peak > worst:
                worst, at = (peak - trade.balance) / peak, f"{trade.closed:%d %b}" if trade.closed else ""
        streak = streak + 1 if trade.outcome == "loss" else 0
        longest = max(longest, streak)
    return [f"- **Since the account started:** largest fall from a balance high {worst * 100:.1f}%"
            + (f" (reached {at})" if at else "") + f"; longest run of losses {longest}."]


def _rows(trades: Sequence[Trade], key: Callable[[Trade], Iterable[str]]) -> list[str]:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        for name in key(trade):
            groups[name].append(trade)
    rows = []
    for name, members in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        rs = [t.r for t in members if t.r is not None]
        money = sum((t.pnl for t in members if t.pnl is not None), Decimal(0))
        rows.append(f"| {name} | {len(members)} | {sum(t.outcome == 'win' for t in members)} | "
                    f"{sum(t.outcome == 'loss' for t in members)} | {sum(rs):+.2f} | "
                    f"{_num(fmean(rs) if rs else None)} | {_money(money)} |")
    return rows


def _bucket(value: float | None, edges: Sequence[tuple[float, str]], missing: str = "not recorded") -> str:
    if value is None:
        return missing
    for edge, name in edges:
        if value < edge:
            return name
    return edges[-1][1]


def breakdown_lines(closed: Sequence[Trade], config: AppConfig) -> list[str]:
    swing = config.analysis.swing_trend_threshold
    groups: list[tuple[str, Callable[[Trade], Iterable[str]]]] = [
        ("Pair", lambda t: [t.symbol]),
        ("Direction", lambda t: [_side(t.side)]),
        ("Pair and direction", lambda t: [t.label]),
        ("Session at entry (a trade can count in two)", lambda t: t.sessions),
        ("Exit", lambda t: [t.exit_reason]),
        ("H4 trend strength", lambda t: [_bucket(t.trend, ((swing, f"below {swing:g} (DAY)"),
                                                           (math.inf, f"{swing:g} or more (SWING)")))]),
        ("Entry location in the 20-hour range, in the trade's direction",
         lambda t: [_bucket(t.extreme, ((0.5, "below 0.5 (a pullback)"), (0.8, "0.5–0.8"),
                                        (math.inf, "0.8 or more (at the extreme)")))]),
        ("Stop width", lambda t: [_bucket(t.stop_atr, ((2, "under 2 × ATR"), (4, "2–4 × ATR"),
                                                       (math.inf, "4 × ATR or more")))]),
    ]
    lines: list[str] = []
    for title, key in groups:
        lines += ["", f"**{title}**", "", "| Group | Trades | Won | Lost | Total R | Average R | A$ |",
                  "|---|---|---|---|---|---|---|", *_rows(closed, key)]
    return lines


def comparison_lines(closed: Sequence[Trade], paths: Mapping[str, Excursion]) -> list[str]:
    wins = [t for t in closed if t.outcome == "win"]
    losses = [t for t in closed if t.outcome == "loss"]
    measures: list[tuple[str, Callable[[Trade], float | None]]] = [
        ("Range position in the trade's direction (1 = at the 20-hour extreme)", lambda t: t.extreme),
        ("H4 trend strength", lambda t: t.trend),
        ("Setup part h1_momentum", lambda t: t.component("h1_momentum")),
        ("Setup part structure", lambda t: t.component("structure")),
        ("Setup part pullback_coherence", lambda t: t.component("pullback_coherence")),
        ("Distance from the H1 20 EMA, ATR in the trade's direction", lambda t: t.ema_distance),
        ("Stop width, × H1 ATR", lambda t: t.stop_atr),
        ("Move in the 24 h before entry, × ATR in the trade's direction",
         lambda t: paths[t.trade_id].prior_move_atr),
        ("Hours held", lambda t: ((t.closed - t.opened).total_seconds() / 3600) if t.closed else None),
        ("Best point while open, R", lambda t: paths[t.trade_id].best),
    ]

    def average(group: Sequence[Trade], measure: Callable[[Trade], float | None]) -> str:
        values = [v for t in group if (v := measure(t)) is not None]
        return f"{fmean(values):.2f} (n={len(values)})" if values else "–"

    return ["| Measured at entry | Winners | Losers |", "|---|---|---|",
            *[f"| {name} | {average(wins, m)} | {average(losses, m)} |" for name, m in measures]]


def overlap_lines(trades: Sequence[Trade], now: datetime) -> list[str]:
    """Trades opened while others were open, with what was already open (same-theme risk)."""
    lines = []
    for trade in trades:
        others = [o for o in trades if o is not trade and o.opened < trade.opened < (o.closed or now)]
        if others:
            lines.append(f"- {trade.opened:%d %b %H:%M} UTC {trade.label} opened while open: "
                         + ", ".join(f"{o.label} (since {o.opened:%d %b %H:%M})" for o in others) + ".")
    usd = {("USDJPY", "LONG"), ("EURUSD", "SHORT"), ("GBPUSD", "SHORT")}
    lines.append("- A buy of USDJPY and a sell of EURUSD or GBPUSD are all bets on a stronger US dollar: "
                 + str(sum((t.symbol, t.side) in usd for t in trades)) + " of these "
                 + str(len(trades)) + " trades were.")
    return lines


def trade_table(trades: Sequence[Trade], paths: Mapping[str, Excursion], now: datetime) -> list[str]:
    lines = [("| # | Opened (UTC) | Trade | Entry | First stop (pips; × ATR) | Exit or now | Exit | Held | "
             "Best R | Result R | A$ |"), "|---|---|---|---|---|---|---|---|---|---|---|"]
    for number, t in enumerate(trades, 1):
        pip = pip_size(t.symbol)
        lines.append(f"| {number} | {t.opened:%d %b %H:%M} | {t.label} | {_price(t.entry, t.symbol)} | "
                     f"{_price(t.first_stop, t.symbol)} ({t.risk / pip:.0f}; {_num(t.stop_atr, '.1f')}) | "
                     f"{_price(t.last, t.symbol)} | {t.exit_reason} | {_held(t, now)} | "
                     f"{_num(paths[t.trade_id].best)} | {_num(t.r)} | {_money(t.pnl)} |")
    return lines


def path_rows(trade: Trade, candles: Sequence[Candle], now: datetime) -> list[str]:
    """4-hour summary of the stored hourly bars, from a day before entry to a day after the exit."""
    end = trade.closed or now
    start, stop = trade.opened - timedelta(hours=24), end + (timedelta(hours=24) if trade.closed else timedelta(0))
    groups: dict[datetime, list[Candle]] = defaultdict(list)
    for c in sorted(candles, key=lambda c: c.timestamp_utc):
        if start <= c.timestamp_utc + HOUR and c.timestamp_utc <= stop:
            groups[c.timestamp_utc.replace(hour=c.timestamp_utc.hour // 4 * 4)].append(c)
    lines = ["| 4 hours from (UTC) | Best R | Worst R | Close R | Note |", "|---|---|---|---|---|"]
    for begin, bars in sorted(groups.items()):
        finish = begin + timedelta(hours=4)
        high, low = max(b.high for b in bars), min(b.low for b in bars)
        best, worst = (high, low) if trade.sign > 0 else (low, high)
        notes = []
        if begin <= trade.opened < finish:
            notes.append(f"ENTRY {trade.opened:%H:%M}")
        if trade.closed and begin <= trade.closed < finish:
            notes.append(f"EXIT {trade.closed:%H:%M} ({trade.exit_reason})")
        if not notes:
            notes.append("before" if finish <= trade.opened else "after exit" if trade.closed and begin > trade.closed
                         else "open")
        if len(bars) < 4:
            notes.append(f"{len(bars)} of 4 hours stored")
        lines.append(f"| {begin:%a %d %b %H:%M} | {_num(trade.r_at(best))} | {_num(trade.r_at(worst))} | "
                     f"{_num(trade.r_at(bars[-1].close))} | {'; '.join(notes)} |")
    return lines if len(lines) > 2 else ["No stored hourly prices cover this trade."]


def detail_lines(number: int, trade: Trade, path: Excursion, candles: Sequence[Candle], now: datetime) -> list[str]:
    pip = pip_size(trade.symbol)
    title = (f"### Trade #{number}: {trade.label}, "
             + (f"{_num(trade.r)} R ({_money(trade.pnl)}), closed by {trade.exit_reason}" if trade.closed else
                f"still open at {_num(trade.r)} R ({_money(trade.pnl)})"))
    regime = trade.candidate.get("h4_regime") or {}
    parts = trade.candidate.get("setup_strength_components") or {}
    lines = [title, "",
             f"- **Opened:** {clock_line(trade.opened)}.",
             (f"- **Closed:** {clock_line(trade.closed)}, after {_held(trade, now)}." if trade.closed else
              f"- **Open for** {_held(trade, now)} so far."),
             f"- **Prices:** entry {_price(trade.entry, trade.symbol)}; first stop {_price(trade.first_stop, trade.symbol)}"
             f" ({trade.risk / pip:.1f} pips = 1 R, {_num(trade.stop_atr, '.1f')} × H1 ATR); "
             + (f"exit {_price(trade.last, trade.symbol)}" if trade.closed else
                f"now {_price(trade.last, trade.symbol)}, stop now {_price(trade.current_stop, trade.symbol)}")
             + f"; target {_price(trade.target, trade.symbol)}; {trade.volume} lots"
             + (f"; spread paid {trade.spread_pips:.1f} pips" if trade.spread_pips is not None else "") + "."]
    if regime or parts:
        lines.append(f"- **Why it entered:** H4 {regime.get('label', '?')}, strength {_num(trade.trend, '.2f')}. "
                     + "Setup parts: " + ", ".join(f"{k} {float(v):.2f}" for k, v in sorted(parts.items()))
                     + (f" (average {fmean(float(v) for v in parts.values()):.2f})" if parts else "") + ".")
        lines.append(f"- **Entry location:** {_num(trade.extreme, '.2f')} of the 20-hour range in the trade's "
                     f"direction (1 = {'bought at the high' if trade.sign > 0 else 'sold at the low'}). "
                     f"{_num(trade.ema_distance, '+.2f')} ATR from the H1 20 EMA in the trade's direction. "
                     f"RSI {_num(trade.feature('h1_rsi'), '.0f')}. Sessions: {', '.join(trade.sessions)}.")
    if trade.review:
        lines.append(f"- **AI news check:** {trade.review.get('status')}: "
                     f"\"{str(trade.review.get('rationale', ''))[:240]}\"")
    lines.append(f"- **Before entry:** price had moved {_num(path.prior_move_atr, '+.1f')} × ATR in the trade's "
                 "direction over the previous 24 hours.")
    lines.append(f"- **While open:** best {_num(path.best)} R"
                 + (f" after {path.best_after_hours:.0f} h" if path.best_after_hours is not None else "")
                 + f", worst {_num(path.worst)} R"
                 + (f"; it gave back {path.best - trade.r:.2f} R from its best" if trade.closed and path.best is not None
                    and trade.r is not None and path.best > trade.r else "") + ".")
    if trade.closed:
        hours = f"{path.after_hours} stored hour{'' if path.after_hours == 1 else 's'}"
        lines.append(f"- **After the exit** ({hours}, in R of the original trade): "
                     f"best {_num(path.after_best)}, worst {_num(path.after_worst)}.")
    return [*lines, "", *path_rows(trade, candles, now)]


def clock_summary(start: date, end: date) -> list[str]:
    """UTC times of the market landmarks on the period's weekdays, noting daylight-saving changes."""
    lines = []
    for name, zone, at in MARKET_EVENTS:
        spans: list[list[Any]] = []
        day = start
        while day <= end:
            if day.weekday() < 5:
                utc = datetime.combine(day, at, ZoneInfo(zone)).astimezone(UTC).strftime("%H:%M")
                if spans and spans[-1][1] == utc:
                    spans[-1][2] = day
                else:
                    spans.append([day, utc, day])
            day += timedelta(days=1)
        if spans:
            lines.append(f"- {name}: " + "; then ".join(
                f"{utc} UTC" + ("" if len(spans) == 1 else f" ({first:%d %b}–{last:%d %b})") for first, utc, last in spans))
    return lines


def build_lookback_prompt(config: AppConfig, journal: JournalStore, candles: Callable[[str], Sequence[Candle]],
                          days: int, now: datetime) -> tuple[str, int, int]:
    """The prompt text, the number of closed trades in the period and the number open now."""
    days = max(1, min(MAX_DAYS, days))
    since = now - timedelta(days=days)
    closed, open_now, everything = load_trades(journal, since)
    trades = sorted([*closed, *open_now], key=lambda t: t.opened)
    bars = {symbol: list(candles(symbol)) for symbol in {t.symbol for t in trades}}
    paths = {t.trade_id: excursion(t, bars[t.symbol], now) for t in trades}
    detailed = trades[-MAX_DETAILED:]
    sydney = ZoneInfo("Australia/Sydney")
    sections = [
        (f"# Trading lookback: {since.astimezone(sydney):%d %b} to {now.astimezone(sydney):%d %b %Y} "
        f"(last {days} days, Sydney dates)"), "",
        (f"Written by the paper bot at {now:%Y-%m-%d %H:%M} UTC (prompt {PROMPT_VERSION}). All prices are the "
        "broker's demo bid prices; R = result in units of the trade's first stop distance."), "",
        INSTRUCTIONS_FILE.read_text(encoding="utf-8").strip(), "", research_text(), "",
        "## How the bot works now", "", *strategy_lines(config), "",
        "## Results at a glance", "", *results_lines(closed, open_now, everything, config, journal), "",
        "## Breakdown of the closed trades",
        *(breakdown_lines(closed, config) if closed else ["", "- No trades closed in this period."]), "",
        "## Winners against losers (averages of what the bot measured at entry)", "",
        *(comparison_lines(closed, paths) if closed else ["- No trades closed in this period."]), "",
        "## Trades open at the same time", "",
        *(overlap_lines(trades, now) if trades else ["- No trades in this period."]), "",
        "## Every trade in the period", "",
        *(trade_table(trades, paths, now) if trades else ["- No trades in this period."]), "",
    ]
    if len(trades) > len(detailed):
        sections += [f"Details follow for the latest {len(detailed)} trades only.", ""]
    first_detailed = len(trades) - len(detailed) + 1
    for number, trade in enumerate(detailed, first_detailed):
        sections += [*detail_lines(number, trade, paths[trade.trade_id], bars[trade.symbol], now), ""]
    sections += [
        "## Market clock in this period", "", *clock_summary(since.date(), now.date()), "",
        "## Not included", "",
        "- Commission and overnight swap: the paper account does not charge them; the spread is real.",
        "- Tick-by-tick prices; prices after the hours stored.",
        "- The bot's code. The rules above fully describe how it enters, places the stop, exits and sizes trades.",
    ]
    return "\n".join(sections) + "\n", len(closed), len(open_now)
