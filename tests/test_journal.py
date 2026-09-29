from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from forex.attribution import attribute
from forex.cloud_sync import SyncWorker
from forex.journal import JournalEvent, JournalStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class Mirror:
    def __init__(self) -> None:
        self.fail = False
        self.remote: dict[str, str] = {}
        self.calls = 0

    def write(self, event: JournalEvent, summary: object, daily: object) -> None:
        self.calls += 1
        if self.fail:
            raise ConnectionError("simulated outage")
        self.remote[event.event_id] = event.payload_hash

    def fingerprint(self, mode: str, event_id: str) -> str | None:
        return self.remote.get(event_id)


def test_every_decision_class_is_retained_and_duplicate_does_not_recount(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "audit.sqlite3")
    for kind in ("candidate", "no_trade", "hard_risk_block", "context_rejection", "execution"):
        first = store.append("PAPER", kind, kind, {"inputs": {"source": "fixture"}}, NOW)
        assert store.append("PAPER", kind, kind, first.payload, NOW + timedelta(days=1)) == first
    assert len(store.events()) == 5
    assert store.summary("PAPER")["event_count"] == 5
    assert len(store.pending(NOW, 100)) == 5
    with pytest.raises(ValueError, match="conflict"):
        store.append("PAPER", "candidate", "candidate", {"changed": True}, NOW)


def test_outbox_failure_rolls_back_event_and_aggregate(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "audit.sqlite3")
    with closing(sqlite3.connect(store.path)) as db, db:
        db.execute("CREATE TRIGGER fail_outbox BEFORE INSERT ON journal_outbox "
                   "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        store.append("PAPER", "candidate", "one", {}, NOW)
    assert store.events() == () and store.summary("PAPER")["event_count"] == 0


def test_reserve_ledger_and_aggregates_are_exact_and_mode_separated(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "audit.sqlite3")
    for identity, pnl in (("win", "100.12"), ("loss", "-50")):
        store.append("PAPER", "trade_closed", identity, {"pnl_aud": pnl,
                     "reserve_percent": "32.5", "pnl_basis": "simulated_incomplete_costs"}, NOW)
    summary = store.summary("PAPER")
    assert summary["realized_pnl_aud"] == "50.12"
    assert summary["reserve_aud"] == "32.539"
    assert summary["wins"] == summary["losses"] == 1
    assert summary["costs_complete"] is False
    assert store.summary("DEMO")["closed_trades"] == 0


def test_outage_retry_restart_and_cloud_divergence_repair(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "audit.sqlite3")
    event = store.append("PAPER", "candidate", "one", {}, NOW)
    mirror = Mirror()
    mirror.fail = True
    worker = SyncWorker(store, mirror, 5, 60)
    assert worker.sync_once(NOW).failed == 1
    assert worker.sync_once(NOW).failed == 0  # Backoff persists, not a busy retry.
    assert store.events()[0] == event
    mirror.fail = False
    restarted = SyncWorker(JournalStore(store.path), mirror, 5, 60)
    assert restarted.sync_once(NOW + timedelta(seconds=5)).delivered == 1
    assert restarted.sync_once(NOW + timedelta(seconds=6)).delivered == 0
    mirror.remote[event.event_id] = "wrong hash"
    assert restarted.reconcile_page(NOW + timedelta(seconds=7)) == (1, event.sequence)
    assert restarted.sync_once(NOW + timedelta(seconds=7)).delivered == 1
    assert mirror.remote[event.event_id] == event.payload_hash


def test_late_events_do_not_roll_back_current_balance_or_health(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "audit.sqlite3")
    store.append("PAPER", "balance", "new", {"balance": "101", "equity": "102"}, NOW)
    store.append("PAPER", "balance", "old", {"balance": "99", "equity": "98"}, NOW - timedelta(days=1))
    assert store.summary("PAPER")["latest_balance"] == "101"


def test_csv_export_neutralizes_formula_identity_and_retains_full_payload(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "audit.sqlite3")
    store.append("PAPER", "no_trade", "=HYPERLINK(fake)", {"reason": "fixture"}, NOW)
    target = tmp_path / "audit.csv"
    assert store.export_csv(target, "PAPER") == 1
    assert "'=HYPERLINK" in target.read_text(encoding="utf-8-sig")
    assert "reason" in target.read_text(encoding="utf-8-sig")


def test_attribution_distinguishes_risk_observations_from_causality() -> None:
    evidence: dict[str, dict[str, Any]] = {
        "risk-1": {"kind": "hard_risk_block", "reason": "portfolio maximum"},
        "trade-1": {"ambiguous": True, "exit_reason": "AMBIGUOUS_STOP_FIRST",
                    "costs_complete": False, "entry_regime": "TREND", "exit_regime": "RANGE"},
        "analysis-1": {"kind": "analysis_no_candidate", "reason": "no setup"},
    }
    labels = attribute(evidence)
    assert len(labels) == 6
    assert all(set(item.evidence_ids) <= set(evidence) for item in labels)
    assert all(item.causal_confidence is None for item in labels)
    assert attribute({}) == ()
