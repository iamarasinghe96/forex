from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from test_cloud_firestore_safe import FakeClient, nested_arrays
from test_learning import runtime_fixture
from test_risk import NOW

from forex.cloud_sync import FirestoreMirror
from forex.domain import Candle, Tick, Timeframe
from forex.learning import TradeFacts, overlay_path
from forex.learning_worker import LearningWorker
from forex.loss_review import market_clock, price_lines
from forex.notifications import NotificationWorker
from forex.telegram_commands import CommandHandler


def closed_trade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, loss: bool = True) -> tuple[Any, Any]:
    """A EURUSD buy opened by the real paper runtime, then closed at a loss (or in profit)."""
    runtime, paper, feed = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()
    if loss:
        feed.tick.return_value = Tick("EURUSD", Decimal("1.085"), Decimal("1.0851"), NOW)  # Below the stop.
        paper.manage(NOW)
    else:
        feed.tick.return_value = Tick("EURUSD", Decimal("1.13"), Decimal("1.1301"), NOW)
        paper.manage(NOW, flatten=True)
    paper.journal_fills(runtime.journal)
    clock = {"now": NOW}
    worker = LearningWorker(lambda: runtime.config, runtime.journal, runtime.learning, None,
                            lambda symbol: runtime.candles.load(symbol, Timeframe.H1), lambda: clock["now"])
    return runtime, (worker, clock)


def prompts(runtime: Any) -> list[Any]:
    return [e for e in runtime.journal.events(limit=1000) if e.kind == "loss_prompt"]


def test_a_loss_gets_one_self_contained_prompt_an_hour_later(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, (worker, clock) = closed_trade(tmp_path, monkeypatch)
    worker.once()
    assert not prompts(runtime)  # The exit hour's bar is not complete yet.
    clock["now"] = NOW + timedelta(hours=1, minutes=1)
    worker.once()
    worker.once()
    [event] = prompts(runtime)  # Written once, however often the worker runs.
    text = event.payload["prompt"]
    assert event.payload["r"] < 0 and event.payload["file_name"].startswith("loss-review-EURUSD-")
    for part in ("# Losing trade review: EURUSD Buy", "## How the bot works now", "So the bot buys strength",
                 "Already tested", "## The losing trade", "## Why the bot took it", "## Hour-by-hour prices",
                 "## Market clock around the trade (UTC)", "## Account and recent trades", "← this trade",
                 "EVIDENCE", "Rules to test (max 3)", "Started at A$"):
        assert part in text, part
    assert "first stop 1.09000" in text and "Sydney" in text
    assert "token" not in text.lower() and str(runtime.config.broker.login) not in text  # No account identifiers.


def test_the_prompt_reaches_telegram_the_command_and_the_dashboard_mirror(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, (worker, clock) = closed_trade(tmp_path, monkeypatch)
    clock["now"] = NOW + timedelta(hours=2)
    worker.once()
    sender = Mock()
    NotificationWorker(runtime.journal, sender).once()
    name, content, caption = sender.send_document.call_args.args
    assert name.endswith(".txt") and content.startswith("# Losing trade review") and "ChatGPT" in caption
    handler = CommandHandler(runtime.base_config, runtime.learning, overlay_path(runtime.paper.path),
                             lambda: NOW, runtime.journal)
    reply = handler.handle("/loss")[0]
    assert reply.document is not None and reply.document[1] == content
    client = FakeClient()
    event = prompts(runtime)[0]
    FirestoreMirror(client).write(event, {"event_count": 1}, {"event_count": 1})
    stored = client.written[("modes", "PAPER", "events", event.event_id)]
    assert not nested_arrays(stored) and stored["payload"]["prompt"] == content


def test_no_prompt_for_wins_or_when_switched_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, (worker, clock) = closed_trade(tmp_path / "win", monkeypatch, loss=False)
    clock["now"] = NOW + timedelta(hours=2)
    worker.once()
    assert not prompts(runtime)
    runtime, (worker, clock) = closed_trade(tmp_path / "off", monkeypatch)
    runtime.config.learning.loss_prompts = False
    clock["now"] = NOW + timedelta(hours=2)
    worker.once()
    assert not prompts(runtime)
    handler = CommandHandler(runtime.base_config, runtime.learning, overlay_path(runtime.paper.path),
                             lambda: NOW, runtime.journal)
    assert "No loss review yet" in handler.handle("/loss")[0].text


def facts(**changes: Any) -> TradeFacts:
    """The 7 Oct 2026 USDJPY buy that hit its stop."""
    values: dict[str, Any] = {
        "trade_id": "t", "symbol": "USDJPY", "side": "LONG", "setup": "TREND_CONTINUATION_BREAKOUT_PULLBACK",
        "regime": "TREND_UP", "style": "DAY", "sessions": ("ASIA",), "volatility": "LOW", "conviction": None,
        "entry": 158.427, "initial_stop": 157.913, "exit": 157.89, "exit_reason": "STOP", "r": -1.04,
        "pnl_aud": -53.7, "opened_at_utc": "2026-10-07T04:00:09+00:00", "closed_at_utc": "2026-10-07T08:15:01+00:00"}
    return TradeFacts(**{**values, **changes})


def test_market_clock_follows_each_city_daylight_saving() -> None:
    lines = "\n".join(market_clock(facts()))
    assert "Wed 07 Oct 00:55 UTC: Tokyo fix" in lines           # 09:55 JST (UTC+9).
    assert "Wed 07 Oct 07:00 UTC: London open" in lines         # 08:00 BST (UTC+1) in October.
    assert "Wed 07 Oct 06:00 UTC: Frankfurt open" in lines      # 08:00 CEST (UTC+2).
    assert "Tue 06 Oct 21:00 UTC: New York close" in lines      # 17:00 EDT (UTC-4).
    assert "gotobi" in lines and "none" in lines.split("gotobi")[1]  # 6-7 Oct are not settlement days.
    winter = "\n".join(market_clock(facts(opened_at_utc="2026-12-09T04:00:00+00:00",
                                          closed_at_utc="2026-12-10T03:00:00+00:00")))
    assert "Wed 09 Dec 08:00 UTC: London open" in winter    # 08:00 GMT in winter.
    assert "10 Dec" in winter.split("gotobi")[1]               # Open through the Tokyo morning of the 10th.
    assert "10 Dec 08:00" not in winter                         # Nothing after the exit.


def test_price_table_marks_the_stop_bar_entry_and_exit_in_r() -> None:
    def bar(hours: int, low: str, high: str = "158.50", close: str = "158.40") -> Candle:
        return Candle("USDJPY", Timeframe.H1, datetime(2026, 10, 7, 4, tzinfo=UTC) + timedelta(hours=hours),
                      Decimal("158.40"), Decimal(high), Decimal(low), Decimal(close), 1, 1, 1)
    candles = [bar(-10, "157.913"), *(bar(h, "158.30") for h in range(-9, 4)), bar(4, "157.85", close="158.10"),
               bar(5, "158.00")]
    text = "\n".join(price_lines(candles, facts()))
    assert "this hour set the stop level" in text
    assert "ENTRY at 04:00" in text and "EXIT (STOP) at 08:15" in text and "after exit" in text
    assert "| -1.12 |" in text  # The 08:00 hour's low (157.85) in R.
