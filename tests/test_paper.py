from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_risk import NOW, account, spec

from forex.analysis import Side
from forex.broker.base import Broker
from forex.domain import Tick
from forex.errors import OperatorError
from forex.execution import OrderIntent
from forex.journal import JournalStore
from forex.operations import SingleWriter, backup_database
from forex.paper import PaperBroker
from forex.runtime import RuntimeStore, read_heartbeat


def setup(tmp_path: Path) -> tuple[PaperBroker, Mock]:
    feed = Mock(spec=Broker)
    feed.account_state.return_value = account()
    feed.market_allows_entries.return_value = True
    feed.resolve_symbol.return_value = spec()
    feed.tick.return_value = Tick("EURUSD", Decimal("1.0999"), Decimal("1.1"), NOW)
    return PaperBroker(tmp_path / "paper.sqlite3", feed, account(), Decimal(10000), 30, Decimal("32.5")), feed


def intent() -> OrderIntent:
    return OrderIntent("paper-1", "candidate-1", "risk-1", 1, "EURUSD", Side.LONG,
                       Decimal(".1"), Decimal("1.1"), Decimal("1.09"), Decimal("1.115"), 12, NOW)


def test_paper_fill_restart_and_duplicate_never_call_real_order_api(tmp_path: Path) -> None:
    paper, feed = setup(tmp_path)
    paper.submit(intent())
    restarted = PaperBroker(paper.path, feed, account(), Decimal(99999), 30, Decimal("32.5"))
    restarted.submit(intent())
    assert len(restarted.positions()) == 1
    assert restarted.state(NOW).balance == Decimal(10000)
    assert restarted.state(NOW).equity < Decimal(10000)  # Actual observed bid/ask spread.
    assert Decimal(restarted.position_status(NOW)[0]["unrealized_pnl_aud"]) < 0
    feed.place_order.assert_not_called()
    feed.modify_position.assert_not_called()
    feed.close_position.assert_not_called()


def test_exit_and_reserve_survive_crash_before_journaling(tmp_path: Path) -> None:
    paper, feed = setup(tmp_path)
    paper.submit(intent())
    feed.tick.return_value = Tick("EURUSD", Decimal("1.12"), Decimal("1.1201"), NOW)
    paper.manage(NOW)
    assert not paper.positions()
    journal = JournalStore(paper.path)
    paper.journal_fills(journal)
    paper.journal_fills(journal)
    assert journal.summary("PAPER")["closed_trades"] == 1
    assert Decimal(journal.summary("PAPER")["realized_pnl_aud"]) == Decimal(200)
    assert Decimal(journal.summary("PAPER")["reserve_aud"]) == Decimal(65)
    closed = next(e for e in journal.events() if e.kind == "trade_closed")
    assert Decimal(closed.payload["pips"]) == Decimal(200)
    assert paper.evidence(NOW, NOW)[0].kind == "DEAL"


def test_breakeven_stop_is_durable_and_open_evidence_immutable(tmp_path: Path) -> None:
    paper, feed = setup(tmp_path)
    paper.submit(intent())
    journal = JournalStore(paper.path)
    paper.journal_fills(journal)
    feed.tick.return_value = Tick("EURUSD", Decimal("1.11"), Decimal("1.1101"), NOW)
    paper.manage(NOW)
    assert paper.positions()[0].stop == Decimal("1.1")
    paper.journal_fills(journal)
    assert journal.events()[0].payload["stop"] == "1.09"
    feed.tick.return_value = Tick("EURUSD", Decimal("1.099"), Decimal("1.0991"), NOW)
    paper.manage(NOW)
    paper.journal_fills(journal)
    assert Decimal(journal.summary("PAPER")["realized_pnl_aud"]) < 0  # Gap is not filled at an invented stop price.


def test_stale_quotes_fail_closed_and_flatten_uses_current_quote(tmp_path: Path) -> None:
    paper, feed = setup(tmp_path)
    paper.submit(intent())
    with pytest.raises(OperatorError, match="stale"):
        paper.manage(NOW + timedelta(minutes=1), flatten=True)
    assert len(paper.positions()) == 1
    paper.manage(NOW, flatten=True)
    assert not paper.positions()
    feed.close_position.assert_not_called()


def test_account_mismatch_and_changed_quote_are_rejected(tmp_path: Path) -> None:
    paper, feed = setup(tmp_path)
    assert paper.submit(replace(intent(), entry=Decimal("1.2"))).status == "REJECTED"
    with pytest.raises(OperatorError, match="another account"):
        PaperBroker(paper.path, feed, replace(account(), login=2), Decimal(1000), 30, Decimal(0))


def test_close_only_market_blocks_paper_entries_but_allows_simulated_exit(tmp_path: Path) -> None:
    paper, feed = setup(tmp_path)
    paper.submit(intent())
    feed.market_allows_entries.return_value = False
    assert paper.snapshot("EURUSD", NOW).entries_allowed is False
    assert paper.submit(replace(intent(), client_id="second")).status == "REJECTED"
    paper.manage(NOW, flatten=True)
    assert not paper.positions()
    feed.place_order.assert_not_called()


def test_process_lock_releases_and_backup_is_consistent(tmp_path: Path) -> None:
    paper, _ = setup(tmp_path)
    lock = tmp_path / "process.lock"
    with (SingleWriter(lock), pytest.raises(OperatorError, match="Another paper"),
          SingleWriter(lock)):
        pass
    with SingleWriter(lock):
        backup_database(paper.path, tmp_path / "backup.sqlite3")
    with pytest.raises(ValueError):
        backup_database(paper.path, paper.path)


def test_crashed_evaluation_is_not_repeated_and_missing_heartbeat_is_unhealthy(tmp_path: Path) -> None:
    paper, _ = setup(tmp_path)
    assert RuntimeStore(paper.path).claim("bar", NOW)
    assert not RuntimeStore(paper.path).claim("bar", NOW + timedelta(hours=1))
    assert not read_heartbeat(tmp_path / "missing.json", NOW, 60)


def test_runtime_real_analysis_no_trade_and_restart(tmp_path: Path) -> None:
    from test_analysis import candles, compact_config

    from forex.config import load_config
    from forex.context import ContextReviewer, ContextStore
    from forex.domain import Timeframe
    from forex.runtime import PaperRuntime

    paper, feed = setup(tmp_path)
    config = load_config(Path("config.yaml"))
    config.analysis = compact_config()
    config.broker.symbols = ["EURUSD"]
    config.execution.session_rollover = None
    config.execution.session_rollover_hour_utc = 0
    config.paper.heartbeat_file = tmp_path / "heartbeat.json"
    config.paper.halt_file = tmp_path / "HALT"
    feed.candles.side_effect = lambda symbol, frame, start, end: candles(
        frame, [1.1] * 60, start=NOW - frame.duration * 60)
    provider = Mock()
    reviewer = ContextReviewer(config.context, provider, ContextStore(paper.path))
    runtime = PaperRuntime(config, feed, paper, reviewer, lambda: NOW)
    runtime.cycle()
    no_trade = [e for e in runtime.journal.events() if e.kind == "no_trade"]
    assert len(no_trade) == 1
    assert read_heartbeat(config.paper.heartbeat_file, NOW, 60)
    # A new process sees the claim and cannot repeat the same decision.
    restarted = PaperRuntime(config, feed, paper, reviewer, lambda: NOW + timedelta(seconds=1))
    restarted.cycle()
    assert len([e for e in runtime.journal.events() if e.kind == "no_trade"]) == 1
    provider.complete.assert_not_called()
    feed.place_order.assert_not_called()
    assert runtime.candles.load("EURUSD", Timeframe.H1)


def test_runtime_halt_flattens_simulation_without_real_orders(tmp_path: Path) -> None:
    from forex.config import load_config
    from forex.context import ContextReviewer, ContextStore
    from forex.runtime import PaperRuntime

    paper, feed = setup(tmp_path)
    paper.submit(intent())
    config = load_config(Path("config.yaml"))
    config.execution.session_rollover = None
    config.execution.session_rollover_hour_utc = 0
    config.paper.heartbeat_file = tmp_path / "heartbeat.json"
    config.paper.halt_file = tmp_path / "HALT"
    config.paper.halt_file.touch()
    runtime = PaperRuntime(config, feed, paper,
                           ContextReviewer(config.context, Mock(), ContextStore(paper.path)), lambda: NOW)
    runtime.cycle()
    assert not paper.positions()
    assert runtime.journal.summary("PAPER")["closed_trades"] == 1
    feed.candles.assert_not_called()
    feed.close_position.assert_not_called()


def test_notification_outage_retains_delivery_cursor(tmp_path: Path) -> None:
    from forex.notifications import NotificationWorker

    paper, _ = setup(tmp_path)
    journal = JournalStore(paper.path)
    journal.append("PAPER", "alert", "one", {"reason": "fixture"}, NOW)
    sender = Mock()
    worker = NotificationWorker(journal, sender)
    sender.send.side_effect = ConnectionError("offline")
    with pytest.raises(ConnectionError):
        worker.once()
    sender.send.side_effect = None
    assert NotificationWorker(journal, sender).once() == 1
    assert worker.once() == 0


@pytest.mark.parametrize("target_rr", [None, 3.0])
def test_candidate_passes_shared_risk_context_execution_and_fill_provenance(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_rr: float | None) -> None:
    from test_analysis import candles, compact_config
    from test_risk import candidate

    from forex.analysis import AnalysisResult, analyse_market
    from forex.config import load_config
    from forex.context import ContextReviewer, ContextStore
    from forex.domain import Timeframe
    from forex.runtime import PaperRuntime

    paper, feed = setup(tmp_path)
    config = load_config(Path("config.yaml"))
    config.analysis = compact_config()
    config.broker.symbols = ["EURUSD"]
    config.context.enabled = False  # Independent of the operator's config.yaml choice.
    config.execution.session_rollover = None
    config.execution.session_rollover_hour_utc = 0
    config.paper.heartbeat_file = tmp_path / "heartbeat.json"
    config.paper.halt_file = tmp_path / "HALT"
    config.paper.target_reward_risk = target_rr
    series = {frame: candles(frame, [1.1] * 60, start=NOW-frame.duration*60) for frame in Timeframe}
    feed.candles.side_effect = lambda symbol, frame, start, end: series[frame]
    snapshot = analyse_market("EURUSD", series[Timeframe.H1], series[Timeframe.H4], NOW, config.analysis).snapshot
    fixture_candidate = replace(candidate(), candidate_id=snapshot.evaluation_id, evaluation_id=snapshot.evaluation_id)
    monkeypatch.setattr("forex.runtime.analyse_market", lambda *args: AnalysisResult(snapshot, fixture_candidate))
    runtime = PaperRuntime(config, feed, paper, ContextReviewer(config.context, Mock(), ContextStore(paper.path)), lambda: NOW)
    runtime.cycle()
    assert len(paper.positions()) == 1
    position = paper.positions()[0]
    assert (position.target - position.entry) / (position.entry - position.stop) >= Decimal(str(target_rr or 1.5))
    assert runtime.trailing_atr["EURUSD"] > 0
    opened = next(e for e in runtime.journal.events() if e.kind == "trade_opened")
    assert set(opened.payload["decision_provenance"]) == {"candidate", "risk_decision", "context_review"}
    assert opened.payload["trade_style"] == "DAY"
    runtime.execution.reconcile(NOW, NOW)
    paper.journal_fills(runtime.journal)
    assert len(paper.positions()) == 1
    feed.place_order.assert_not_called()


def test_health_journal_is_throttled_but_heartbeat_file_is_fresh(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="forex.paper")
    from forex.config import load_config
    from forex.context import ContextReviewer, ContextStore
    from forex.runtime import PaperRuntime

    paper, feed = setup(tmp_path)
    config = load_config(Path("config.yaml"))
    config.context.enabled = False
    config.execution.session_rollover = None
    config.execution.session_rollover_hour_utc = 0
    config.paper.heartbeat_file = tmp_path / "heartbeat.json"
    config.paper.halt_file = tmp_path / "HALT"
    config.paper.health_journal_seconds = 60
    runtime = PaperRuntime(config, feed, paper, ContextReviewer(config.context, Mock(), ContextStore(paper.path)),
                           lambda: NOW)

    def health() -> list[str]:
        return [e.payload["status"] for e in runtime.journal.events() if e.kind == "health"]

    runtime.heartbeat(NOW, "RUNNING")
    runtime.heartbeat(NOW + timedelta(seconds=5), "RUNNING")
    assert health() == ["RUNNING"]
    assert caplog.text.count("Running | balance AUD") == 1
    assert read_heartbeat(config.paper.heartbeat_file, NOW + timedelta(seconds=5), 1)
    runtime.heartbeat(NOW + timedelta(seconds=10), "HALTED")  # Status change is recorded at once.
    runtime.heartbeat(NOW + timedelta(seconds=70), "HALTED")
    runtime.heartbeat(NOW + timedelta(seconds=71), "HALTED")
    assert health() == ["RUNNING", "HALTED", "HALTED"]
    assert len([e for e in runtime.journal.events() if e.kind == "balance"]) == 3


def test_persistent_cycle_failure_is_reported_once_then_hourly_then_recovered(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from threading import Event

    from forex.config import load_config
    from forex.context import ContextReviewer, ContextStore
    from forex.runtime import PaperRuntime

    paper, feed = setup(tmp_path)
    config = load_config(Path("config.yaml"))
    config.context.enabled = config.cloud.enabled = config.telegram.enabled = False
    config.execution.session_rollover = None
    config.execution.session_rollover_hour_utc = 0
    config.paper.heartbeat_file = tmp_path / "heartbeat.json"
    config.paper.halt_file = tmp_path / "HALT"
    config.paper.poll_seconds = 0.001
    config.paper.error_repeat_seconds = 3600
    ticks = iter(range(10_000))
    runtime = PaperRuntime(config, feed, paper, ContextReviewer(config.context, Mock(), ContextStore(paper.path)),
                           lambda: NOW + timedelta(seconds=5 * next(ticks)))
    outcomes = [OperatorError("stale")] * 800 + [None]  # ~66 minutes of 5-second failures, then healthy.

    def cycle() -> None:
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome
    monkeypatch.setattr(runtime, "cycle", cycle)
    runtime.run(Event(), maximum_cycles=801)
    errors = [e.payload for e in runtime.journal.events() if e.kind == "error"]
    # First reported once the failure has lasted error_grace_seconds (30 s), then hourly.
    assert [e["consecutive_failed_cycles"] for e in errors] == [7, 727]
    alerts = [e.payload["reason"] for e in runtime.journal.events() if e.kind == "alert"]
    assert len(alerts) == 1 and alerts[0].startswith("Recovered after 800 failed cycles (OperatorError)")
    feed.place_order.assert_not_called()


def test_quote_slightly_newer_than_cycle_time_is_accepted(tmp_path: Path) -> None:
    paper, feed = setup(tmp_path)
    paper.submit(intent())
    feed.tick.return_value = Tick("EURUSD", Decimal("1.0999"), Decimal("1.1"), NOW + timedelta(seconds=0.4))
    assert paper.state(NOW).equity  # A tick received after the cycle started is not stale.
    feed.tick.return_value = Tick("EURUSD", Decimal("1.0999"), Decimal("1.1"), NOW + timedelta(seconds=60))
    with pytest.raises(OperatorError, match="stale or invalid"):
        paper.state(NOW)


def test_brief_flapping_failures_do_not_alert_the_phone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from threading import Event

    from forex.config import load_config
    from forex.context import ContextReviewer, ContextStore
    from forex.runtime import PaperRuntime

    paper, feed = setup(tmp_path)
    config = load_config(Path("config.yaml"))
    config.context.enabled = config.cloud.enabled = config.telegram.enabled = False
    config.execution.session_rollover = None
    config.execution.session_rollover_hour_utc = 0
    config.paper.heartbeat_file = tmp_path / "heartbeat.json"
    config.paper.halt_file = tmp_path / "HALT"
    config.paper.poll_seconds = 0.001
    ticks = iter(range(10_000))
    runtime = PaperRuntime(config, feed, paper, ContextReviewer(config.context, Mock(), ContextStore(paper.path)),
                           lambda: NOW + timedelta(seconds=5 * next(ticks)))
    outcomes = [OperatorError("Paper quote is stale or invalid."), None] * 20

    def cycle() -> None:
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome
    monkeypatch.setattr(runtime, "cycle", cycle)
    runtime.run(Event(), maximum_cycles=40)
    kinds = [e.kind for e in runtime.journal.events()]
    assert "error" not in kinds and "alert" not in kinds


def test_optional_atr_trailing_stop_starts_after_one_r(tmp_path: Path) -> None:
    paper, feed = setup(tmp_path)
    paper.submit(intent())  # Entry 1.1, stop 1.09 (1R = 0.01).
    atr = {"EURUSD": Decimal("0.002")}
    feed.tick.return_value = Tick("EURUSD", Decimal("1.105"), Decimal("1.1051"), NOW)
    paper.manage(NOW, atr_by_symbol=atr, atr_multiple=Decimal(2))
    assert paper.positions()[0].stop == Decimal("1.09")  # Below +1R: unchanged.
    feed.tick.return_value = Tick("EURUSD", Decimal("1.111"), Decimal("1.1111"), NOW)
    paper.manage(NOW, atr_by_symbol=atr, atr_multiple=Decimal(2))
    assert paper.positions()[0].stop == Decimal("1.107")  # Bid minus 2 x ATR.
    feed.tick.return_value = Tick("EURUSD", Decimal("1.109"), Decimal("1.1091"), NOW)
    paper.manage(NOW, atr_by_symbol=atr, atr_multiple=Decimal(2))
    assert paper.positions()[0].stop == Decimal("1.107")  # Never loosens.


def test_quiet_quote_pauses_entries_and_exits_without_failing(tmp_path: Path) -> None:
    paper, feed = setup(tmp_path)
    paper.submit(intent())
    # No tick for 60 s (e.g. the 17:00 New York rollover) with the price past the target.
    feed.tick.return_value = Tick("EURUSD", Decimal("1.12"), Decimal("1.1201"), NOW - timedelta(seconds=60))
    assert not paper.quote_fresh("EURUSD", NOW)
    assert paper.snapshot("EURUSD", NOW).entries_allowed is False
    assert paper.state(NOW).equity > Decimal(10000)  # Valued at the last valid price.
    paper.manage(NOW)
    assert len(paper.positions()) == 1  # Not closed on an old price; re-checked next cycle.
    with pytest.raises(OperatorError, match="stale"):
        paper.manage(NOW, flatten=True)


def test_runtime_rides_out_quiet_quotes_and_reports_long_silence(tmp_path: Path) -> None:
    from forex.config import load_config
    from forex.context import ContextReviewer, ContextStore
    from forex.runtime import PaperRuntime

    paper, feed = setup(tmp_path)
    config = load_config(Path("config.yaml"))
    config.broker.symbols = ["EURUSD"]
    config.context.enabled = False
    config.execution.session_rollover = None
    config.execution.session_rollover_hour_utc = 0
    config.paper.heartbeat_file = tmp_path / "heartbeat.json"
    config.paper.halt_file = tmp_path / "HALT"
    clock = [NOW]
    runtime = PaperRuntime(config, feed, paper, ContextReviewer(config.context, Mock(), ContextStore(paper.path)),
                           lambda: clock[0])
    runtime.next_analysis = NOW + timedelta(hours=1)
    feed.tick.return_value = Tick("EURUSD", Decimal("1.0999"), Decimal("1.1"), NOW - timedelta(seconds=60))
    runtime.cycle()  # Quiet for a minute: no failure and no market-permission alert.
    assert not [e for e in runtime.journal.events() if e.kind == "alert"]
    clock[0] = NOW + timedelta(seconds=config.paper.stale_quote_alert_seconds + 1)
    with pytest.raises(OperatorError, match="No fresh EURUSD quote"):
        runtime.cycle()
    feed.tick.return_value = Tick("EURUSD", Decimal("1.0999"), Decimal("1.1"), clock[0])
    runtime.cycle()
    assert not runtime.stale_since
