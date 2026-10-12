from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from test_learning import runtime_fixture
from test_risk import NOW

from forex.config import load_config
from forex.domain import Candle, Tick, Timeframe
from forex.journal import JournalStore
from forex.learning import LearningStore, overlay_path
from forex.lookback import build_lookback_prompt, clock_summary
from forex.persistence import CandleStore
from forex.telegram_commands import CommandHandler

T0 = datetime(2026, 10, 5, 0, tzinfo=UTC)


def candidate(symbol: str, side: str, range_position: float, trend: float, atr: float) -> dict[str, Any]:
    return {"symbol": symbol, "side": side, "setup_type": "TREND_CONTINUATION_BREAKOUT_PULLBACK",
            "trade_style": "DAY", "style_reason": "H1 continuation", "session_context": ["ASIA"],
            "volatility_context": 0.3,
            "h4_regime": {"label": "TREND_UP" if side == "LONG" else "TREND_DOWN", "trend_strength": trend,
                          "directional_bias": 0.5 if side == "LONG" else -0.5},
            "setup_strength_components": {"h4_trend": trend, "h1_momentum": 0.2, "structure": 0.6,
                                          "pullback_coherence": 0.5},
            "feature_snapshot": {"h1_range_position": range_position, "h1_atr": atr,
                                 "h1_distance_fast_atr": 0.9 if side == "LONG" else -0.9, "h1_rsi": 60.0}}


def trade(journal: JournalStore, trade_id: str, symbol: str, side: str, opened: datetime, entry: str,
          stop: str, cand: dict[str, Any], close: tuple[datetime, str, str, str, str] | None = None) -> None:
    provenance = {"candidate": {"candidate": cand, "strategy_version": "4977cb76"},
                  "context_review": {"review": {"status": "APPROVED", "rationale": "No conflicting news."}}}
    intent = {"stop": stop, "side": side, "candidate_id": "c-" + trade_id}
    position = {"client_id": trade_id, "symbol": symbol + ".a", "side": side, "entry": entry, "stop": stop,
                "target": "1.0", "volume": "0.10"}
    journal.append("PAPER", "trade_opened", trade_id, {**position, "decision_provenance": provenance,
                                                       "intent": intent}, opened)
    journal.append("PAPER", "execution", "c-" + trade_id, {"symbol": symbol, "entry_spread_pips": 0.3,
                                                          "entry_spread_r": 0.01}, opened)
    if close:
        closed, exit_, pnl, balance, stop_at_close = close
        journal.append("PAPER", "trade_closed", trade_id, {
            "position": {**position, "stop": stop_at_close}, "symbol": symbol + ".a", "entry": entry, "exit": exit_,
            "volume": "0.10", "opened_at_utc": opened.isoformat(), "closed_at_utc": closed.isoformat(),
            "pnl_aud": pnl, "balance": balance, "pips": "0", "direction": side, "reserve_percent": "32.5",
            "reason": "STOP", "pnl_basis": "simulated_incomplete_costs", "costs_complete": False,
            "decision_provenance": provenance, "intent": intent}, closed)


def bars(symbol: str, start: datetime, closes: list[float], spread: float) -> list[Candle]:
    return [Candle(symbol, Timeframe.H1, start + timedelta(hours=i), Decimal(str(c)), Decimal(str(round(c + spread, 5))),
                   Decimal(str(round(c - spread, 5))), Decimal(str(c)), 1, 1, 1) for i, c in enumerate(closes)]


@pytest.fixture
def journal(tmp_path: Path) -> JournalStore:
    store = JournalStore(tmp_path / "paper.sqlite3")
    # A EURUSD sell that trailed into profit, a USDJPY buy stopped out, and a EURUSD sell still open.
    trade(store, "win", "EURUSD", "SHORT", T0 + timedelta(hours=2), "1.12000", "1.12500",
          candidate("EURUSD", "SHORT", 0.1, 0.72, 0.0010), (T0 + timedelta(hours=30), "1.11400", "37.41", "1037.41",
                                                            "1.11400"))
    trade(store, "loss", "USDJPY", "LONG", T0 + timedelta(hours=52), "158.427", "157.913",
          candidate("USDJPY", "LONG", 0.82, 0.673, 0.115), (T0 + timedelta(hours=56, minutes=15), "157.890",
                                                            "-53.70", "983.71", "157.913"))
    trade(store, "open", "EURUSD", "SHORT", T0 + timedelta(hours=54), "1.11750", "1.12653",
          candidate("EURUSD", "SHORT", 0.05, 0.70, 0.0012))
    store.append("PAPER", "health", "h1", {"positions": [{"client_id": "open", "market_price": "1.12274",
                                                          "unrealized_pnl_aud": "-30.04", "stop": "1.12653"}]},
                 T0 + timedelta(hours=80))
    store.append("PAPER", "balance", "b1", {"balance": "983.71", "equity": "953.67"}, T0 + timedelta(hours=80))
    candles = CandleStore(store.path)
    eurusd = [1.1230 - 0.0002 * i for i in range(40)] + [1.1175 + 0.0001 * i for i in range(50)]
    candles.upsert(bars("EURUSD", T0 - timedelta(hours=10), eurusd, 0.0004))
    candles.upsert(bars("USDJPY", T0 + timedelta(hours=26), [158.10 + 0.012 * i for i in range(27)]
                        + [158.30, 158.10, 157.95, 158.00, 158.05], 0.06))
    return store


def prompt(journal: JournalStore, days: int = 14) -> str:
    candles = CandleStore(journal.path)
    text, _, _ = build_lookback_prompt(load_config(Path("config.yaml")), journal,
                                       lambda s: candles.load(s, Timeframe.H1), days, T0 + timedelta(hours=81))
    return text


def test_lookback_reports_results_breakdowns_and_each_trade(journal: JournalStore) -> None:
    text = prompt(journal)
    for part in ("# Trading lookback:", "## What I need from you", "Already tested", "## How the bot works now",
                 "## Results at a glance", "## Breakdown of the closed trades", "## Winners against losers",
                 "## Trades open at the same time", "## Every trade in the period", "## Market clock in this period"):
        assert part in text, part
    assert "**Closed trades:** 2 (1 won, 1 lost, 0 about break-even" in text and "Open now: 1." in text
    assert "**Total:** +0.16 R, A$-16.29." in text           # +1.20 R and -1.04 R.
    assert "**inside** that range" in text                    # Two trades cannot show a difference.
    assert "| USDJPY Buy | 1 | 0 | 1 | -1.04 | -1.04 | A$-53.70 |" in text
    assert "0.8 or more (at the extreme)" in text and "below 0.5 (a pullback)" not in text
    assert "### Trade #2: USDJPY Buy, -1.04 R (A$-53.70), closed by STOP" in text
    assert "### Trade #3: EURUSD Sell, still open at -0.58 R (A$-30.04)" in text
    assert "it gave back" in text and "spread paid 0.3 pips" in text
    assert "EURUSD Sell opened while open: USDJPY Buy" in text
    assert "3 of these 3 trades were" in text                  # All three bet on a stronger US dollar.
    assert "London open: 07:00 UTC" in text                    # Early October: British summer time.
    assert "23011822" not in text                              # No account number.


def test_lookback_period_and_empty_case(journal: JournalStore) -> None:
    assert "**Closed trades:** 1 (0 won, 1 lost" in prompt(journal, days=2)  # The win closed 3 days ago.
    assert "No trades closed in this period." in prompt(journal, days=1)    # The loss closed 25 h ago.
    empty = JournalStore(journal.path.with_name("empty.sqlite3"))
    text = prompt(empty)
    assert "No trades closed in this period." in text and "No trades in this period." in text


def test_market_clock_notes_the_daylight_saving_changes() -> None:
    lines = "\n".join(clock_summary(date(2026, 10, 20), date(2026, 11, 3)))
    assert "London open: 07:00 UTC (20 Oct–23 Oct); then 08:00 UTC (26 Oct–03 Nov)" in lines
    assert "New York open: 12:00 UTC (20 Oct–30 Oct); then 13:00 UTC (02 Nov–03 Nov)" in lines
    assert "Tokyo fix: 00:55 UTC" in lines and "Tokyo fix: 00:55 UTC (" not in lines  # Japan has no DST.


def test_telegram_lookback_uses_the_bots_own_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, paper, feed = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()
    feed.tick.return_value = Tick("EURUSD", Decimal("1.085"), Decimal("1.0851"), NOW)
    paper.manage(NOW)
    paper.journal_fills(runtime.journal)
    handler = CommandHandler(runtime.base_config, runtime.learning, overlay_path(paper.path),
                             lambda: NOW + timedelta(hours=1), runtime.journal)
    reply = handler.handle("/lookback 7")[0]
    assert reply.document is not None and reply.document[0].startswith("lookback-")
    assert "1 closed trades, 0 open" in reply.text
    assert "### Trade #1: EURUSD Buy, -1.50 R" in reply.document[1]
    assert "last 90 days" in handler.handle("/lookback 999")[0].document[1]  # type: ignore[index]
    no_journal = CommandHandler(runtime.base_config, LearningStore(tmp_path / "x.sqlite3"),
                                overlay_path(tmp_path / "x.sqlite3"), lambda: NOW)
    assert "not available" in no_journal.handle("/lookback")[0].text
