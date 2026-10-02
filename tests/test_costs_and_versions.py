from __future__ import annotations

import importlib.util
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_learning import runtime_fixture
from test_paper import setup
from test_risk import NOW

from forex.config import load_config
from forex.costs import CostRecorder
from forex.domain import SwapRates, Tick
from forex.learning import (
    LEGACY_VERSION,
    LearningStore,
    TradeFacts,
    apply_overlay,
    bucket_scores,
    sizing_decision,
    strategy_version,
)
from forex.learning_worker import LearningWorker


def facts(trade_id: str, r: float, version: str = LEGACY_VERSION, symbol: str = "EURUSD") -> TradeFacts:
    return TradeFacts(trade_id, symbol, "LONG", "TREND_CONTINUATION_BREAKOUT_PULLBACK", "TREND_UP",
                      "INTRADAY", ("LONDON",), "MEDIUM", 60.0, 1.1, 1.09, 1.1 + 0.01 * r, "STOP", r, 10 * r,
                      NOW.isoformat(), (NOW + timedelta(hours=3)).isoformat(), version)


def report_module():
    spec = importlib.util.spec_from_file_location("cost_report", Path("scripts/cost_report.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_settings_version_tracks_signal_and_exit_settings_only() -> None:
    base = load_config(Path("config.yaml"))
    version = strategy_version(base)
    assert strategy_version(apply_overlay(base, {"risk": {"risk_percent_per_trade": 1}})) == version
    assert strategy_version(apply_overlay(base, {"learning": {"min_trades": 50}})) == version
    assert strategy_version(apply_overlay(base, {"exits": {"target_reward_risk": 3}})) != version
    assert strategy_version(apply_overlay(base, {"analysis": {"trend_efficiency_window": 15}})) != version


def test_scores_are_never_pooled_across_settings_versions(tmp_path: Path) -> None:
    store = LearningStore(tmp_path / "paper.sqlite3")
    for i in range(3):
        store.record_trade(facts(f"old-{i}", -1.0, "aaaa1111"), NOW)
    store.record_trade(facts("new-1", 2.0, "bbbb2222"), NOW)
    store.record_trade(facts("legacy", 1.0), NOW)
    assert store.scores(20, "bbbb2222")["all"].trades == 1
    assert store.scores(20, "aaaa1111")["pair:EURUSD"].total_r == pytest.approx(-3)
    assert store.scores(20)["all"].trades == 5  # None pools everything (for display only).
    summary = {v.version: (v.trades, v.total_r) for v in store.versions()}
    assert summary == {"aaaa1111": (3, -3.0), "bbbb2222": (1, 2.0), LEGACY_VERSION: (1, 1.0)}


def test_ordinary_losing_streak_does_not_shrink_size_but_a_reliable_one_does() -> None:
    keys = ["all", "pair:EURUSD"]
    # 30 trades at a 34% win rate with 1.5R winners: average -0.15 R, well inside the noise.
    streak = [facts(f"t{i}", 1.5 if i % 3 == 0 else -1.0) for i in range(30)]
    noisy = bucket_scores(streak, 20)
    assert noisy["all"].average_r < 0 and noisy["all"].std_error >= 1 / 30 ** 0.5
    held = sizing_decision(noisy, keys, min_trades=10, min_factor=0.25, skip_below_r=None, evidence_z=2.5)
    assert held.factor == 1 and "no bucket is reliably losing" in held.reason
    assert sizing_decision(noisy, keys, min_trades=10, min_factor=0.25, skip_below_r=None).factor < 1
    # 40 straight full losses: the average stays far below 0 R even after 2.5 standard errors.
    awful = bucket_scores([facts(f"l{i}", -1.0) for i in range(40)], 20)
    assert awful["all"].std_error == pytest.approx(1 / 40 ** 0.5)  # Spread floored at 1 R.
    shrunk = sizing_decision(awful, keys, min_trades=10, min_factor=0.25, skip_below_r=None, evidence_z=2.5)
    assert shrunk.factor < 1 and not shrunk.skip


def test_runtime_tags_trades_with_the_settings_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, paper, feed = runtime_fixture(tmp_path, monkeypatch)
    feed.swap_rates.return_value = SwapRates("EURUSD", -7.5, 2.1, 1, 3)
    runtime.cycle()
    version = strategy_version(runtime.config)
    candidate = next(e for e in runtime.journal.events(limit=500) if e.kind == "candidate")
    assert candidate.payload["strategy_version"] == version
    execution = next(e for e in runtime.journal.events(limit=500) if e.kind == "execution")
    assert execution.payload["entry_spread_pips"] == pytest.approx(1.0)
    assert 0 < execution.payload["entry_spread_r"] < 1
    feed.tick.return_value = Tick("EURUSD", Decimal("1.085"), Decimal("1.0851"), NOW)
    paper.manage(NOW)
    paper.journal_fills(runtime.journal)
    LearningWorker(lambda: runtime.config, runtime.journal, runtime.learning, None, lambda s: [], lambda: NOW).once()
    assert runtime.learning.trades()[0].strategy_version == version
    assert runtime.learning.scores(20, version)["all"].trades == 1
    assert "all" not in runtime.learning.scores(20, "other")
    review = next(e for e in runtime.journal.events(limit=500) if e.kind == "trade_review")
    assert f"settings {version}" in review.payload["message"]
    assert runtime.costs.pending  # This hour's spread samples are waiting for the hour to end.


def test_cost_sampling_failure_never_stops_trading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, paper, feed = runtime_fixture(tmp_path, monkeypatch)
    feed.swap_rates.side_effect = RuntimeError("MT5 hiccup")
    runtime.costs.pending[((NOW - timedelta(hours=1)).isoformat(), "EURUSD")] = [1.0]
    runtime.costs.broker_names["EURUSD"] = "EURUSD"
    runtime.cycle()
    assert len(paper.positions()) == 1


def test_cost_recorder_writes_finished_hours_with_swap(tmp_path: Path) -> None:
    paper, _ = setup(tmp_path)
    recorder = CostRecorder(paper.path)
    start = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    for i, ask in enumerate(["1.10010", "1.10012", "1.10030"]):
        recorder.observe("EURUSD", "EURUSD.a", Tick("EURUSD.a", Decimal("1.1"), Decimal(ask), start),
                         Decimal("0.0001"), start + timedelta(minutes=i))
    swaps = {"EURUSD.a": SwapRates("EURUSD.a", -7.5, 2.1, 1, 3)}
    assert recorder.flush(start + timedelta(minutes=30), swaps.get) == 0  # Hour still in progress.
    assert recorder.flush(start + timedelta(hours=1), swaps.get) == 1
    with sqlite3.connect(paper.path) as db:
        row = db.execute("SELECT * FROM cost_hours").fetchone()
    assert row[:3] == ("2026-01-05T09:00:00+00:00", "EURUSD", 3)
    assert row[3:7] == pytest.approx((5.2 / 3, 1.2, 3.0, 3.0))
    assert row[7:] == (-7.5, 2.1, 1, 3)
    assert recorder.pending == {}


def test_rollover_nights_count_weekdays_and_the_triple_day() -> None:
    nights = report_module().rollover_nights
    monday = datetime(2026, 1, 5, 17, 0, tzinfo=UTC)  # 12:00 New York.
    assert nights(monday, monday + timedelta(days=3), 3) == 5  # Mon, Tue, Wed x3.
    friday = monday + timedelta(days=4)
    assert nights(friday, friday + timedelta(days=3), 3) == 1  # Friday only; no weekend rollovers.
    assert nights(monday, monday + timedelta(hours=2), 3) == 0


def test_cost_report_runs_on_a_recorded_paper_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    paper, _ = setup(tmp_path)
    recorder = CostRecorder(paper.path)
    hour = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    recorder.observe("EURUSD", "EURUSD", Tick("EURUSD", Decimal("1.1"), Decimal("1.10011"), hour),
                     Decimal("0.0001"), hour)
    recorder.flush(hour + timedelta(hours=1), lambda s: SwapRates(s, -7.5, 2.1, 1, 3))
    from test_paper import intent
    paper.submit(replace(intent(), created_at_utc=NOW))
    module = report_module()
    monkey = pytest.MonkeyPatch()
    monkey.setattr("sys.argv", ["cost_report.py", "--db", str(paper.path)])
    try:
        assert module.main() == 0
    finally:
        monkey.undo()
    out = capsys.readouterr().out
    assert "EURUSD" in out and "1.10" in out and "Overnight swap" in out
    assert "Applied to 1 paper trades" in out
