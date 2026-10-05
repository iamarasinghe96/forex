from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_cloud_firestore_safe import FakeClient, nested_arrays
from test_learning import runtime_fixture
from test_risk import NOW

from forex.cloud_sync import FirestoreMirror
from forex.domain import Tick


def charts(runtime) -> list:  # type: ignore[no-untyped-def]
    return [e for e in runtime.journal.events(limit=1000) if e.kind == "position_chart"]


def test_open_trades_carry_entry_time_initial_stop_and_r(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, paper, feed = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()
    feed.tick.return_value = Tick("EURUSD", Decimal("1.11"), Decimal("1.1101"), NOW)  # Price moved up.
    status = paper.position_status(NOW)[0]
    entry, initial = Decimal(status["entry"]), Decimal(status["initial_stop"])
    assert status["opened_at_utc"] == NOW.isoformat()
    assert Decimal(status["r_multiple"]) == ((Decimal("1.11") - entry) / (entry - initial)).quantize(Decimal("0.01"))


def test_chart_is_published_hourly_and_when_open_trades_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, _, _ = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()  # Opens a trade after the chart was published for "no open trades".
    published = charts(runtime)
    assert [len(e.payload["positions"]) for e in published] == [0]
    runtime.publish_position_chart(NOW)  # The open trade changes the set: publish again.
    latest = charts(runtime)[-1].payload["positions"]
    assert len(latest) == 1
    chart = latest[0]
    assert chart["side"] == "LONG" and chart["opened_at_utc"] == NOW.isoformat()
    bars = chart["bars"]
    assert len(bars["t"]) == len(bars["h"]) == len(bars["l"]) == len(bars["c"]) > 0
    assert all(isinstance(v, int) for v in bars["t"]) and bars["t"] == sorted(bars["t"])
    runtime.publish_position_chart(NOW + timedelta(minutes=20))  # Same hour, same trades: nothing new.
    assert len(charts(runtime)) == 2
    runtime.publish_position_chart(NOW + timedelta(hours=1))      # Next hour: refreshed.
    assert len(charts(runtime)) == 3


def test_chart_failure_never_interrupts_trading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, paper, feed = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()
    feed.candles.side_effect = RuntimeError("MT5 hiccup")
    runtime.publish_position_chart(NOW + timedelta(hours=2))
    assert len(paper.positions()) == 1


def test_mirror_keeps_the_latest_chart_in_one_dashboard_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, _, _ = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()
    runtime.publish_position_chart(NOW)
    event = charts(runtime)[-1]
    client = FakeClient()
    FirestoreMirror(client).write(event, {"event_count": 1}, {"event_count": 1})
    document = client.written[("modes", "PAPER", "aggregates", "chart")]
    assert not nested_arrays(document)
    assert document["sequence"] == event.sequence and len(document["positions"]) == 1
