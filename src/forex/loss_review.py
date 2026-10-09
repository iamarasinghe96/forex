"""A self-contained ChatGPT prompt for every losing paper trade.

After a loss the operator asks ChatGPT for an outside opinion. ChatGPT cannot see this repository,
so each prompt carries everything it needs:
- the review instructions and the research so far (a prompt file the developer keeps current);
- the bot's rules, generated from the live settings;
- the trade, and the bot's own reasons for taking it;
- the hourly prices around the trade;
- the market clock;
- the account's recent trades.

The prompt is stored as a ``loss_prompt`` journal event. Telegram sends it as a file, and the
dashboard shows a copy button. Nothing here calls an AI service or changes trading.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from forex.config import AppConfig
from forex.domain import Candle
from forex.journal import JournalEvent, JournalStore
from forex.learning import TradeFacts, price_path, strategy_version, trade_facts

PROMPT_VERSION = "loss-review-chatgpt-v1"
DELAY = timedelta(hours=1)      # Wait for the exit hour's bar, so the price table includes it.
LOOKBACK = timedelta(days=14)   # Older losses (e.g. from before this feature) get no prompt.
BARS_BEFORE, BARS_AFTER, MAX_OPEN_BARS = 24, 24, 96
HOUR = timedelta(hours=1)
CITIES = (("Sydney", "Australia/Sydney"), ("Tokyo", "Asia/Tokyo"), ("London", "Europe/London"),
          ("New York", "America/New_York"))
MARKET_EVENTS = (
    ("Tokyo open", "Asia/Tokyo", time(9, 0)),
    ("Tokyo fix", "Asia/Tokyo", time(9, 55)),
    ("Frankfurt open", "Europe/Berlin", time(8, 0)),
    ("London open", "Europe/London", time(8, 0)),
    ("New York open", "America/New_York", time(8, 0)),
    ("usual time of major US data releases", "America/New_York", time(8, 30)),
    ("London 4 pm fix", "Europe/London", time(16, 0)),
    ("New York close / daily rollover (thin market, wider spreads)", "America/New_York", time(17, 0)),
)


def _d(value: Any) -> Decimal | None:
    try:
        return None if value is None else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _f(value: Any) -> float | None:
    number = _d(value)
    return None if number is None else float(number)


def pip_size(symbol: str) -> Decimal:
    return Decimal("0.01") if symbol.upper().split(".")[0].endswith("JPY") else Decimal("0.0001")


def _price(value: Any, symbol: str) -> str:
    number = _d(value)
    return "?" if number is None else f"{number:.{3 if symbol.endswith('JPY') else 5}f}"


def _side(side: str) -> str:
    return "Buy" if side == "LONG" else "Sell"


def clock_line(moment: datetime) -> str:
    local = ", ".join(f"{name} {moment.astimezone(ZoneInfo(zone)):%a %H:%M}" for name, zone in CITIES)
    return f"{moment:%a %d %b %Y %H:%M} UTC ({local})"


def _duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    days, hours, minutes = minutes // 1440, minutes % 1440 // 60, minutes % 60
    return " ".join(part for part in (f"{days} d" if days else "", f"{hours} h" if hours else "",
                                      f"{minutes} min" if minutes and not days else "") if part) or "under a minute"


def strategy_lines(config: AppConfig, facts: TradeFacts) -> list[str]:
    """The live rules in plain words, with every number taken from the settings."""
    a, p, r, lc, ctx = config.analysis, config.paper, config.risk, config.learning, config.context
    version = strategy_version(config)
    pairs = [s for s in config.broker.symbols if s.upper() not in {d.upper() for d in lc.disabled_pairs}]
    risks = sorted({float(v) for v in r.conviction_risk_percent.values()})
    risk_text = (f"{risks[0]:g}% of the balance" if len(risks) == 1 else
                 "by confidence: " + ", ".join(f"{k} {float(v):g}%" for k, v in r.conviction_risk_percent.items()))
    efficiency = a.trend_efficiency_window or a.structure_window
    providers = ", ".join(provider.name for provider in ctx.providers) or "none configured"
    lines = [
        f"Settings version {version}"
        + ("" if version == facts.strategy_version else
           f" (this trade was taken under version {facts.strategy_version}; the rules below are the current ones)")
        + ".", "",
        "**Account and data**",
        (f"- Paper account in Australian dollars, started at A${p.starting_balance_aud:,.0f}. Prices come from the "
        "IC Markets MT5 demo feed, and no order ever reaches a broker."),
        f"- Pairs traded: {', '.join(pairs)}.",
        "- The bot decides once an hour, right after each 1-hour (H1) bar closes.",
        (f"- 4-hour (H4) bars are built from H1 bars at "
        f"{', '.join(f'{(config.market_data.h4_alignment_hour_utc + 4 * i) % 24:02d}' for i in range(6))} UTC."),
        "",
        "**Entry** (only trend-continuation setups are allowed"
        + ("; range trading is off)" if list(a.allowed_setups) == ["TREND_CONTINUATION_BREAKOUT_PULLBACK"] else ")"),
        "1. H4 trend filter.",
        ("   - Direction (−1 to +1) combines three things: the gap between the "
        f"{a.ema_fast}/{a.ema_slow} EMAs, the slope of the {a.ema_fast} EMA, and the last 5 bars' up/down count."),
        f"   - Efficiency = net move ÷ total distance travelled over the last {efficiency} H4 bars.",
        "   - Strength = 0.45 × |direction| + 0.55 × efficiency.",
        (f"   - A trade needs strength ≥ {a.trend_threshold:g} and |direction| > 0.15. The bot buys only in an "
        "up-trend and sells only in a down-trend."),
        "   - " + ("Trends are not traded in the top 10% of volatility." if a.high_volatility_blocks_trend else
                   "Strong trends are traded even in the top 10% of volatility (the volatility block is off)."),
        f"2. H1 setup score ≥ {a.setup_score_threshold:g}. The score is the average of four parts:",
        "   - **h4_trend:** the H4 trend strength.",
        ("   - **h1_momentum:** the H1 MACD histogram in the trade's direction (tanh of histogram ÷ ATR; "
        "0 if it points the other way)."),
        (f"   - **structure:** where the last H1 close sits in the high–low range of the {a.structure_window} H1 bars "
        "before it. It is highest for buys at or above the top of the range and for sells at or below the bottom, "
        "and 0 in the opposite half. **So the bot buys strength and sells weakness; it does not wait for a "
        "pullback.**"),
        f"   - **pullback_coherence:** closeness to the H1 {a.ema_fast} EMA (1 = on it, 0 = 3 ATR away).",
        f"3. Label only: SWING if H4 strength ≥ {a.swing_trend_threshold:g}, otherwise DAY. Both use the same exits.",
        "4. Limits:",
        f"   - at most {p.max_positions_per_pair} open trade(s) per pair;",
        f"   - at most {r.max_concurrent_positions} open trades;",
        f"   - at most {r.max_simultaneous_risk_percent:g}% of the balance at risk in total;",
        (f"   - if equity falls {r.daily_loss_percent:g}% below the day's opening balance, every trade is closed "
         "and none opens until the next trading day (New York close)."),
        ("5. AI news check before entry. A language model (" + providers + ") reads the trade and current "
         "context and may approve, shrink or reject it. It can never enlarge a trade." if ctx.enabled else
         "5. No AI news check before entry."),
        "   The bot has no economic calendar and no live news feed.",
        "",
        "**Stop, exits and size**",
        (f"- **Stop:** for buys, the lowest low of the {a.structure_window} H1 bars before the signal bar; for "
        "sells, the highest high. No extra buffer is added. 1 R = the distance from entry to this stop."),
        ("- **After +1 R:** the stop moves to the entry price, then trails "
         f"{p.atr_trailing_multiple:g} × H1 ATR(14) behind the price." if p.atr_trailing_multiple else
         "- **After +1 R:** the stop moves to the entry price. There is no trailing stop."),
        (f"- **Target:** {p.target_reward_risk:g} R. It is rarely reached; the trailing stop normally ends the "
         "trade." if p.target_reward_risk else "- **Target:** 1.5 R.")
        + " There is no time limit and no exit for news.",
        f"- **Size:** {risk_text} is lost if the stop is hit."
        + (f" The size is cut if the free margin at {r.max_leverage}:1 leverage does not allow it."
           if r.enforce_margin else ""),
        ("- **Learning:** each closed trade updates scores by pair, trend, session and so on. A group trades "
         f"smaller (down to {lc.min_factor:.0%} of normal) only after {lc.min_trades}+ trades with a clearly "
         "negative average." if lc.enabled and lc.apply_to_sizing else
         "- **Learning:** results are recorded but do not change trade size."),
        (f"- **Paper fills:** entries are at the live ask (buys) or bid (sells). The stop is checked every "
        f"{p.poll_seconds:g} s, and the trade closes at the first quote at or beyond it. The real spread is paid; "
        "commission and overnight swap are not charged."),
    ]
    return lines


def _plan(provenance: Mapping[str, Any]) -> Mapping[str, Any]:
    review = ((provenance.get("context_review") or {}).get("review") or {})
    risk = ((provenance.get("risk_decision") or {}).get("risk") or {})
    return review.get("plan") or risk.get("permitted_position_plan") or {}


def trade_lines(event: JournalEvent, facts: TradeFacts) -> list[str]:
    payload, symbol = event.payload, facts.symbol
    opened, closed = datetime.fromisoformat(facts.opened_at_utc), datetime.fromisoformat(facts.closed_at_utc)
    pnl, balance = _d(payload.get("pnl_aud")) or Decimal(0), _d(payload.get("balance"))
    pip = pip_size(symbol)
    risk_pips = abs(Decimal(str(facts.entry)) - Decimal(str(facts.initial_stop))) / pip
    moved = (Decimal(str(facts.exit)) - Decimal(str(facts.entry))) / pip * (1 if facts.side == "LONG" else -1)
    plan = _plan(payload.get("decision_provenance") or {})
    planned = _f(plan.get("actual_risk_percent"))
    beyond = (Decimal(str(facts.initial_stop)) - Decimal(str(facts.exit))) / pip * (1 if facts.side == "LONG" else -1)
    volume = (payload.get("position") or {}).get("volume", payload.get("volume", "?"))
    lines = [
        f"- **Pair and direction:** {symbol} {_side(facts.side)}, {volume} lots.",
        f"- **Opened:** {clock_line(opened)}.",
        f"- **Closed:** {clock_line(closed)}, by {facts.exit_reason}, after {_duration(closed - opened)}.",
        "- **Prices:**",
        f"  - entry {_price(facts.entry, symbol)};",
        f"  - first stop {_price(facts.initial_stop, symbol)} ({risk_pips:.1f} pips = 1 R);",
        f"  - exit {_price(facts.exit, symbol)} ({moved:+.1f} pips);",
        f"  - target {_price((payload.get('position') or {}).get('target'), symbol)}.",
        f"- **Result:** {facts.r:+.2f} R = A${pnl:+.2f}."
        + (f" Balance A${balance - pnl:,.2f} → A${balance:,.2f}." if balance is not None else ""),
    ]
    if planned is not None:
        lines.append(f"- **Planned risk:** {planned * 100:.1f}% of the balance"
                     + (f" (A${_d(plan.get('actual_risk_amount')):.2f})" if _d(plan.get("actual_risk_amount")) else "")
                     + ".")
    if beyond > 0:
        lines.append(f"- **Slippage:** the exit filled {beyond:.1f} pips beyond the stop. Paper fills use the first "
                     "quote past the stop.")
    return lines


def entry_lines(event: JournalEvent, facts: TradeFacts, journal: JournalStore) -> list[str]:
    provenance = event.payload.get("decision_provenance") or {}
    candidate_event = provenance.get("candidate") or {}
    candidate = candidate_event.get("candidate") or {}
    regime = candidate.get("h4_regime") or {}
    components = candidate.get("setup_strength_components") or {}
    features = candidate.get("feature_snapshot") or {}
    pip = pip_size(facts.symbol)
    atr = _f(features.get("h1_atr"))

    def value(name: str, scale: float = 1.0, fmt: str = ".2f") -> str:
        number = _f(features.get(name))
        return "?" if number is None else format(number * scale, fmt)

    lines = []
    if regime:
        lines.append(f"- **H4 trend:** {regime.get('label')}.")
        lines.append(f"  - strength {_f(regime.get('trend_strength')) or 0:.2f};")
        lines.append(f"  - direction {_f(regime.get('directional_bias')) or 0:+.2f};")
        lines.append(f"  - H4 volatility rank {_f(regime.get('volatility_state')) or 0:.2f} "
                     "(1 = most volatile of the last 100 bars).")
    if components:
        mean = sum(float(v) for v in components.values()) / len(components)
        lines.append(f"- **Setup score:** {mean:.2f}. Its parts:")
        lines += [f"  - {k} {float(v):.2f}" for k, v in sorted(components.items())]
    if "h1_range_position" in features:
        lines.append("- **H1 position in the 20-hour range:** " + value("h1_range_position")
                     + " (0 = at the low, 1 = at the high; outside 0–1 means the last bar broke out).")
        lines.append("- **H1 range edges:** 20-hour high " + _price(features.get("h1_rolling_high"), facts.symbol)
                     + ", 20-hour low " + _price(features.get("h1_rolling_low"), facts.symbol) + ".")
        lines.append(f"- **Distance from the H1 20 EMA:** {value('h1_distance_fast_atr', fmt='+.2f')} ATR.")
        lines.append("- **H1 indicators:**")
        lines.append(f"  - RSI(14) {value('h1_rsi', fmt='.0f')};")
        histogram = _f(features.get("h1_macd_histogram"))
        lines.append("  - MACD histogram "
                     + (f"{histogram / atr:+.2f}" if histogram is not None and atr else "?") + " ATR;")
        lines.append("  - ATR(14) " + ("?" if atr is None else f"{Decimal(str(atr)) / pip:.1f}") + " pips;")
        lines.append(f"  - volatility rank {value('h1_volatility_rank')}.")
    if candidate:
        lines.append(f"- **Style:** {candidate.get('trade_style')} ({candidate.get('style_reason')}).")
        lines.append(f"- **Sessions open at entry:** {', '.join(candidate.get('session_context') or ['none'])}.")
        opposing = [e.get("detail") or e.get("code") for e in candidate.get("opposing_evidence") or []]
        if opposing:
            lines.append(f"- **Warnings the bot recorded:** {'; '.join(str(o) for o in opposing)}.")
    review = (provenance.get("context_review") or {}).get("review") or {}
    if review:
        lines.append(f"- **AI news check:** {review.get('status')} by {review.get('provider') or 'rules'}: "
                     f"\"{str(review.get('rationale', ''))[:400]}\"")
    score = candidate_event.get("setup_score") or {}
    if score.get("status") == "available":
        lines.append(f"- Setup-score model (shadow only, not used for sizing): {score.get('score_0_100')}/100.")
    intent = event.payload.get("intent") or {}
    execution = journal.find("PAPER", "execution", str(intent.get("candidate_id", ""))) if intent else None
    if execution is not None and execution.payload.get("entry_spread_pips") is not None:
        lines.append(f"- **Spread paid at entry:** {float(execution.payload['entry_spread_pips']):.1f} pips "
                     f"({float(execution.payload.get('entry_spread_r') or 0):.2f} R).")
    return lines or ["- The bot's entry record is unavailable for this trade."]


def price_lines(candles: Sequence[Candle], facts: TradeFacts) -> list[str]:
    """Hourly bars from a day before entry to a day after the exit (those stored so far), in R."""
    symbol = facts.symbol
    opened, closed = datetime.fromisoformat(facts.opened_at_utc), datetime.fromisoformat(facts.closed_at_utc)
    sign = 1 if facts.side == "LONG" else -1
    entry, stop = Decimal(str(facts.entry)), Decimal(str(facts.initial_stop))
    risk, pip = abs(entry - stop), pip_size(symbol)
    if risk == 0:
        return ["- Unavailable: the trade has no stop distance."]
    ordered = sorted(candles, key=lambda c: c.timestamp_utc)
    before = [c for c in ordered if c.timestamp_utc + HOUR <= opened][-BARS_BEFORE:]
    during = [c for c in ordered if c.timestamp_utc + HOUR > opened and c.timestamp_utc <= closed]
    after = [c for c in ordered if c.timestamp_utc > closed][:BARS_AFTER]
    if not before and not during:
        return ["- No stored hourly prices cover this trade."]

    def r(price: Decimal) -> str:
        return f"{(price - entry) * sign / risk:+.2f}"

    def row(c: Candle, note: str) -> str:
        best, worst = (c.high, c.low) if sign > 0 else (c.low, c.high)
        sydney = c.timestamp_utc.astimezone(ZoneInfo("Australia/Sydney"))
        return (f"| {c.timestamp_utc:%a %d %b %H:%M} | {sydney:%a %H:%M} | {_price(c.open, symbol)} | "
                f"{_price(c.high, symbol)} | {_price(c.low, symbol)} | {_price(c.close, symbol)} | "
                f"{r(best)} | {r(worst)} | {r(c.close)} | {note} |")

    lines = [("Each row is one hour; times are the hour's start. R = distance from the entry price in units of "
             "the first stop: +1.00 = one stop-distance in profit, −1.00 = at the stop. \"Best\" and \"worst\" "
             "are the hour's most favourable and least favourable prices for this trade."), "",
             "| UTC | Sydney | Open | High | Low | Close | Best R | Worst R | Close R | Note |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for c in before:
        extreme = c.low if sign > 0 else c.high
        lines.append(row(c, "before; this hour set the stop level" if abs(extreme - stop) < pip / 2 else "before"))
    shown = during if len(during) <= MAX_OPEN_BARS else during[:MAX_OPEN_BARS // 2] + during[-MAX_OPEN_BARS // 2:]
    for index, c in enumerate(shown):
        if len(during) > MAX_OPEN_BARS and index == MAX_OPEN_BARS // 2:
            lines.append(f"| … | | | | | | | | | {len(during) - MAX_OPEN_BARS} hours not shown |")
        notes = []
        if c.timestamp_utc <= opened < c.timestamp_utc + HOUR:
            notes.append(f"ENTRY at {opened:%H:%M}")
        if c.timestamp_utc <= closed < c.timestamp_utc + HOUR:
            notes.append(f"EXIT ({facts.exit_reason}) at {closed:%H:%M}")
        lines.append(row(c, "; ".join(notes) or "open"))
    if not [c for c in during if c.timestamp_utc <= closed < c.timestamp_utc + HOUR]:
        lines.append("| | | | | | | | | | The exit hour's bar was not stored yet when this was written. |")
    lines += [row(c, "after exit") for c in after]
    if before:
        move = (before[-1].close - before[0].open) * sign / pip
        lines += ["", (f"In the {len(before)} hours before entry the price moved {move:+.1f} pips in the trade's "
                      "direction (+ = it had already moved the trade's way).")]
    path = price_path(facts, ordered)
    if path:
        lines.append(f"While open (about {path['bars_held']} hourly bars): best {path['best_excursion_r']:+.2f} R, "
                     f"worst {path['worst_excursion_r']:+.2f} R. Hourly highs and lows include the part of the entry "
                     "hour before the fill.")
    lines.append(f"Hours stored after the exit: {len(after)}"
                 + (" (none yet: look up later prices in public data if they matter)." if not after else "."))
    return lines


def market_clock(facts: TradeFacts) -> list[str]:
    """Session landmarks in UTC from a day before entry to the exit (first and last day of long trades).

    Daylight saving is handled per city.
    """
    opened, closed = datetime.fromisoformat(facts.opened_at_utc), datetime.fromisoformat(facts.closed_at_utc)
    windows = ((opened - timedelta(hours=24), min(opened + timedelta(hours=24), closed)),
               (max(closed - timedelta(hours=24), opened), closed))
    found: set[tuple[datetime, str]] = set()
    day: date = (opened - timedelta(days=2)).date()
    while day <= closed.date() + timedelta(days=1):
        if day.weekday() < 5:
            for name, zone, at in MARKET_EVENTS:
                moment = datetime.combine(day, at, ZoneInfo(zone)).astimezone(UTC)
                if any(start <= moment <= end for start, end in windows):
                    found.add((moment, name))
        day += timedelta(days=1)
    lines = [f"- {moment:%a %d %b %H:%M} UTC: {name}" for moment, name in sorted(found)]
    if facts.symbol.endswith("JPY"):
        tokyo_days = sorted({m.astimezone(ZoneInfo("Asia/Tokyo")).date() for m, n in found if n.startswith("Tokyo")})
        lines.append("- Japanese settlement (\"gotobi\") days among these: "
                     + (", ".join(f"{d:%d %b}" for d in tokyo_days if d.day % 5 == 0) or "none")
                     + " (5th, 10th, 15th, 20th, 25th, 30th).")
    return lines or ["- No weekday market landmarks in this window."]


def account_lines(config: AppConfig, journal: JournalStore, event: JournalEvent) -> list[str]:
    closed_events = [e for e in journal.of_kind("PAPER", "trade_closed", limit=5000)
                     if e.observed_at_utc <= event.observed_at_utc]
    rows = []
    for item in closed_events:
        pnl = _d(item.payload.get("pnl_aud")) or Decimal(0)
        balance = _d(item.payload.get("balance"))
        facts = trade_facts(item.entity_id, item.payload)
        symbol = str(item.payload.get("symbol", "?")).upper().split(".")[0]
        side = _side(str(item.payload.get("direction") or (facts.side if facts else "")))
        r_text = f"{facts.r:+.2f} R" if facts else "? R"
        mark = " ← this trade" if item.entity_id == event.entity_id else ""
        rows.append(f"| {item.observed_at_utc:%d %b %H:%M} | {symbol} {side} | {item.payload.get('reason', '?')} | "
                    f"{r_text} | A${pnl:+.2f} | {'?' if balance is None else f'A${balance:,.2f}'}{mark} |")
    lines = [(f"Started at A${config.paper.starting_balance_aud:,.0f}. Closed trades so far "
             f"({len(rows)}; latest {min(len(rows), 15)} shown):"), "",
             "| Closed (UTC) | Trade | Exit | R | A$ | Balance after |", "|---|---|---|---|---|---|", *rows[-15:]]
    closed_ids = {e.entity_id for e in closed_events}
    still_open = [e for e in journal.of_kind("PAPER", "trade_opened", limit=5000)
                  if e.observed_at_utc <= event.observed_at_utc and e.entity_id not in closed_ids]
    lines += ["", "Other trades open when this one closed: " + ("none." if not still_open else "")]
    for item in still_open:
        p = item.payload
        symbol = str(p.get("symbol", "?")).upper().split(".")[0]
        lines.append(f"- {symbol} {_side(str(p.get('side')))} since {item.observed_at_utc:%d %b %H:%M} UTC, entry "
                     f"{_price(p.get('entry'), symbol)}, first stop {_price(p.get('stop'), symbol)}.")
    return lines


def build_loss_prompt(config: AppConfig, instructions: str, event: JournalEvent, candles: Sequence[Candle],
                      journal: JournalStore, now: datetime) -> tuple[str, TradeFacts]:
    facts = trade_facts(event.entity_id, event.payload)
    if facts is None:
        raise ValueError("closed trade has no decision record")
    closed = datetime.fromisoformat(facts.closed_at_utc)
    title = (f"# Losing trade review: {facts.symbol} {_side(facts.side)}, closed {closed:%d %b %Y} — "
             f"{facts.r:+.2f} R (A${float(event.payload.get('pnl_aud', 0)):+.2f})")
    sections = [
        title, "",
        f"Written by the paper bot at {now:%Y-%m-%d %H:%M} UTC (prompt {PROMPT_VERSION}).", "",
        instructions.strip(), "",
        "## How the bot works now", "", *strategy_lines(config, facts), "",
        "## The losing trade", "", *trade_lines(event, facts), "",
        "## Why the bot took it (its own record at the time)", "", *entry_lines(event, facts, journal), "",
        "## Hour-by-hour prices (the broker's demo bid prices)", "", *price_lines(candles, facts), "",
        "## Market clock around the trade (UTC)", "", *market_clock(facts), "",
        "## Account and recent trades", "", *account_lines(config, journal, event), "",
        "## Not included", "",
        "- Tick-by-tick prices and the broker's order book.",
        "- Prices after the hours stored above. Use public data for later prices.",
        "- The bot's code. The rules above fully describe how it enters, places the stop, exits and sizes trades.",
    ]
    return "\n".join(sections) + "\n", facts


def loss_prompt_payload(config: AppConfig, event: JournalEvent, candles: Sequence[Candle],
                        journal: JournalStore, now: datetime) -> dict[str, Any]:
    instructions = config.learning.loss_prompt_file.read_text(encoding="utf-8")
    prompt, facts = build_loss_prompt(config, instructions, event, candles, journal, now)
    closed = datetime.fromisoformat(facts.closed_at_utc)
    return {"symbol": facts.symbol, "side": facts.side, "r": round(facts.r, 4),
            "pnl_aud": str(event.payload.get("pnl_aud")), "opened_at_utc": facts.opened_at_utc,
            "closed_at_utc": facts.closed_at_utc, "prompt_version": PROMPT_VERSION,
            "file_name": f"loss-review-{facts.symbol}-{closed:%Y-%m-%d-%H%M}.txt", "prompt": prompt}


def losses_without_prompt(journal: JournalStore, limit: int = 200) -> list[JournalEvent]:
    """Recent losing trades that have no review prompt yet (reads no clock)."""
    prompted = {e.entity_id for e in journal.of_kind("PAPER", "loss_prompt", limit=2 * limit)}
    return [e for e in journal.of_kind("PAPER", "trade_closed", limit=limit)
            if e.entity_id not in prompted and (_d(e.payload.get("pnl_aud")) or Decimal(0)) < 0]


def due(event: JournalEvent, now: datetime) -> bool:
    """Closed at least an hour ago (so its exit bar is stored) and within the last two weeks."""
    return now - LOOKBACK <= event.observed_at_utc <= now - DELAY
