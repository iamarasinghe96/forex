import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from forex.intelligence import (
    STAGES,
    AcceptanceCriteria,
    ExperimentEvidence,
    ExperimentRegistry,
    diagnose,
    file_hash,
)
from forex.journal import JournalStore

CREATED = datetime(2026, 1, 2, tzinfo=UTC)
NOW = CREATED + timedelta(days=10)


def proposal(tmp_path: Path) -> tuple[ExperimentRegistry, str]:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    for kind in ("candidate", "no_trade", "hard_risk_block", "context_rejection"):
        journal.append("PAPER", kind, kind, {"reason": "synthetic test fixture"}, CREATED)
    diagnosis = diagnose(journal, "PAPER", CREATED, NOW)
    assert diagnosis["event_counts"]["no_trade"] == 1
    criteria = AcceptanceCriteria(minimum_history_years=5, minimum_walk_forward_folds=2,
        minimum_out_of_sample_trades=10, minimum_shadow_hours=24, minimum_paper_hours=24,
        minimum_net_expectancy_r=0.1, maximum_drawdown_percent=15)
    registry = ExperimentRegistry(tmp_path / "registry.sqlite3")
    version = registry.propose(diagnosis, "Fixture hypothesis, not a strategy recommendation",
                               {"test_parameter": 1}, criteria, CREATED)
    return registry, version


def evidence(tmp_path: Path, version: str, stage: str, **changes: object) -> Path:
    source = tmp_path / "synthetic-fixture.txt"
    source.write_text("SYNTHETIC TEST ONLY", encoding="utf-8")
    start, end = datetime(2019, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)
    if stage == "OOS":
        start, end = datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)
    if stage == "SHADOW":
        start, end = CREATED, CREATED + timedelta(days=1)
    if stage == "PAPER":
        start, end = CREATED + timedelta(days=1), CREATED + timedelta(days=2)
    values = {"version_hash": version, "stage": stage, "producer": "SYNTHETIC_TEST",
                  "code_sha": "a" * 40, "dataset_fingerprint": "synthetic-only",
                  "start_utc": start, "end_utc": end, "generated_at_utc": NOW,
                  "baseline_comparison": "fixture", "costs_complete": True,
                  "broker_h4_alignment_verified": True, "future_data_excluded": True, "history_years": 5,
                  "walk_forward_folds": 2, "completed_trades": 10, "net_expectancy_r": 0.2,
                  "maximum_drawdown_percent": 10, "untouched_oos": True, "real_elapsed_hours": 24,
                  "operational_failures_resolved": True, "source_artifacts": {source.name: file_hash(source)}}
    values.update(changes)
    path = tmp_path / f"{stage}.json"
    path.write_text(ExperimentEvidence.model_validate(values).model_dump_json(), encoding="utf-8")
    return path


def test_missing_gates_cannot_promote_and_no_configuration_is_created(tmp_path: Path) -> None:
    registry, version = proposal(tmp_path)
    result = registry.evaluate(version, NOW)
    assert result["state"] == "BLOCKED" and len(result["issues"]) == 6
    assert result["production_action"] == "NONE"
    with pytest.raises(ValueError, match="complete evidence"):
        registry.record_review(version, "operator", "review-reference", NOW)
    assert not (tmp_path / "config.yaml").exists()


def test_complete_declared_evidence_only_reaches_operator_review(tmp_path: Path) -> None:
    registry, version = proposal(tmp_path)
    for stage in STAGES:
        registry.attach(version, evidence(tmp_path, version, stage), NOW)
    assert registry.evaluate(version, NOW)["state"] == "READY_FOR_OPERATOR_REVIEW"
    registry.record_review(version, "fixture-operator", "synthetic-review", NOW)
    assert registry.evaluate(version, NOW)["production_action"] == "NONE"


@pytest.mark.parametrize("change", [{"costs_complete": False}, {"broker_h4_alignment_verified": False},
    {"untouched_oos": False}, {"completed_trades": 1}, {"net_expectancy_r": -0.1}])
def test_cost_alignment_holdout_sample_and_expectancy_fail_closed(tmp_path: Path, change: dict) -> None:
    registry, version = proposal(tmp_path)
    registry.attach(version, evidence(tmp_path, version, "OOS", **change), NOW)
    assert any(issue.startswith("OOS:") for issue in registry.evaluate(version, NOW)["issues"])


def test_report_or_source_tampering_invalidates_previous_gate(tmp_path: Path) -> None:
    registry, version = proposal(tmp_path)
    path = evidence(tmp_path, version, "HISTORICAL")
    registry.attach(version, path, NOW)
    (tmp_path / "synthetic-fixture.txt").write_text("changed", encoding="utf-8")
    assert any("invalid" in issue for issue in registry.evaluate(version, NOW)["issues"])
    data = json.loads(path.read_text())
    data["history_years"] = 99
    path.write_text(json.dumps(data))
    assert any("changed" in issue for issue in registry.evaluate(version, NOW)["issues"])


def test_fake_elapsed_time_and_replacing_stage_are_rejected(tmp_path: Path) -> None:
    registry, version = proposal(tmp_path)
    with pytest.raises(ValueError, match="wall-clock"):
        evidence(tmp_path, version, "PAPER", real_elapsed_hours=100)
    registry.attach(version, evidence(tmp_path, version, "PAPER"), NOW)
    with pytest.raises(ValueError, match="immutable"):
        registry.attach(version, evidence(tmp_path, version, "PAPER", net_expectancy_r=0.4), NOW)


def test_overlapping_holdout_is_detected(tmp_path: Path) -> None:
    registry, version = proposal(tmp_path)
    registry.attach(version, evidence(tmp_path, version, "HISTORICAL", end_utc=CREATED), NOW)
    registry.attach(version, evidence(tmp_path, version, "OOS"), NOW)
    assert any("overlaps" in issue for issue in registry.evaluate(version, NOW)["issues"])
