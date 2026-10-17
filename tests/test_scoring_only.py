from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_cloud_firestore_safe import FakeClient, nested_arrays
from test_learning import runtime_fixture
from test_risk import NOW

from forex.cloud_sync import FirestoreMirror
from forex.config import load_config
from forex.domain import Tick
from forex.learning import overlay_path
from forex.telegram_commands import CommandHandler


def test_live_setting_is_scoring_only() -> None:
    assert load_config(Path("config.yaml")).paper.entry_strategy == "none"  # Operator decision, 17 Oct 2026.


def test_scoring_only_opens_nothing_but_records_the_old_signal_and_scorecard(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, paper, _ = runtime_fixture(tmp_path, monkeypatch)
    runtime.config.paper.entry_strategy = "none"
    runtime.cycle()
    assert not paper.positions()
    events = runtime.journal.events(limit=1000)
    assert not [e for e in events if e.kind in {"candidate", "risk_decision", "execution", "trade_opened"}]
    [skipped] = [e for e in events if e.kind == "no_trade"]
    assert skipped.payload["reason"] == "Scoring only: no entry strategy is active (the old trend rules would buy)"
    [card] = [e for e in events if e.kind == "scorecard"]
    pair = card.payload["pairs"][0]
    assert card.payload["entry_strategy"] == "none" and pair["symbol"] == "EURUSD"
    assert pair["old_strategy"]["verdict"] == "BUY" and pair["old_strategy"]["stop"] is not None
    assert {"regime", "strength", "direction"} <= set(pair["h4"]) and "range_position" in pair["h1"]
    # Telegram /scorecard and the dashboard document carry it.
    handler = CommandHandler(runtime.base_config, runtime.learning, overlay_path(paper.path), lambda: NOW,
                             runtime.journal)
    text = handler.handle("/scorecard")[0].text
    assert "EURUSD: H4" in text and "old strategy would BUY" in text and "not traded" in text
    client = FakeClient()
    FirestoreMirror(client).write(card, {"event_count": 1}, {"event_count": 1})
    document = client.written[("modes", "PAPER", "aggregates", "scorecard")]
    assert not nested_arrays(document) and document["pairs"][0]["symbol"] == "EURUSD"
    # No "no fills for a week" alert while no strategy is meant to trade.
    runtime.periodic_evidence(NOW + timedelta(days=30))
    assert not [e for e in runtime.journal.events(limit=1000) if e.kind == "alert"]


def test_open_trades_keep_their_stops_after_switching_to_scoring_only(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, paper, feed = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()                                   # Opened under the old strategy.
    assert len(paper.positions()) == 1
    runtime.config.paper.entry_strategy = "none"
    feed.tick.return_value = Tick("EURUSD", Decimal("1.085"), Decimal("1.0851"), NOW)  # Below the stop.
    runtime.cycle()
    assert not paper.positions()                      # The stop still closed it.
    assert [e for e in runtime.journal.events(limit=1000) if e.kind == "trade_closed"]


def test_no_scorecard_yet(tmp_path: Path) -> None:
    from forex.journal import JournalStore
    from forex.learning import LearningStore
    journal = JournalStore(tmp_path / "paper.sqlite3")
    handler = CommandHandler(load_config(Path("config.yaml")), LearningStore(journal.path),
                             overlay_path(journal.path), lambda: NOW, journal)
    assert "No scorecard yet" in handler.handle("/scorecard")[0].text
