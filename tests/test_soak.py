from datetime import UTC, datetime, timedelta
from pathlib import Path

from forex.journal import JournalStore
from forex.soak import summarize_soak

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_empty_or_single_heartbeat_never_claims_elapsed_soak(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "paper.sqlite3")
    assert summarize_soak(store, NOW, NOW + timedelta(days=7))["state"] == "NO_ELAPSED_EVIDENCE"
    store.append("PAPER", "health", "one", {"status": "RUNNING"}, NOW)
    report = summarize_soak(store, NOW, NOW + timedelta(days=7))
    assert report["observed_wall_clock_hours"] == 0
    assert report["operational_failures_resolved"] is False


def test_missing_intervals_and_halts_are_not_counted_as_running(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "paper.sqlite3")
    for seconds, status in ((0, "RUNNING"), (60, "RUNNING"), (3600, "RUNNING"), (3660, "HALTED")):
        store.append("PAPER", "health", str(seconds), {"status": status}, NOW + timedelta(seconds=seconds))
    report = summarize_soak(store, NOW, NOW + timedelta(days=1))
    assert report["running_intervals_supported_by_heartbeats_hours"] == 1 / 60
    assert len(report["unobserved_gaps"]) == 1
    assert report["state"] == "EVIDENCE_REQUIRES_REVIEW"
    assert report["strategy_validated"] is False


def test_clock_reversal_and_version_changes_remain_visible(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "paper.sqlite3")
    store.append("PAPER", "health", "new", {"status": "RUNNING", "config_fingerprint": "new"}, NOW + timedelta(minutes=1))
    store.append("PAPER", "health", "old", {"status": "RUNNING", "config_fingerprint": "old"}, NOW)
    report = summarize_soak(store, NOW, NOW + timedelta(days=1))
    assert report["clock_reversal_detected"] is True
    assert report["config_fingerprints"] == ["new", "old"]
