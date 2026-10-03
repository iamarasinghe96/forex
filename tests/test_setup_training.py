from __future__ import annotations

import csv
import hashlib
import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sklearn")
sys.path.insert(0, str(Path("scripts").resolve()))
from setup_score_training import (
    MODEL_ORDER,
    Opportunity,
    Prediction,
    audit_invariance,
    batch_predictions,
    equity_comparison,
    fit_model,
    purged_split,
    read_datasets,
    scorecard_period,
    transfer_predictions,
)

from forex.config import AnalysisConfig, ScoringConfig
from forex.scoring import FEATURE_SCHEMA, ScoreModel


def rows(n=300, year=2010):
    rng = random.Random(1234)
    result = []
    for i in range(n):
        position = rng.random()
        features = {"h4_directional_efficiency": rng.random(), "h1_range_position": position,
                    "h1_volatility_rank": rng.random(), "style_swing": float(i % 2), "h4_trend_strength": rng.random()}
        decision = datetime(year, 1, 1, tzinfo=UTC) + timedelta(hours=i * 12)
        result.append(Opportunity(decision, decision + timedelta(hours=6), "EURUSD", position - 0.4, 0.01, features))
    return result


@pytest.mark.parametrize("kind", MODEL_ORDER)
def test_portable_models_fit_calibrate_and_pass_invariance(kind: str, tmp_path: Path) -> None:
    model = fit_model(kind, rows(), rows(100, 2011), "test", ScoringConfig())
    path = tmp_path / f"{kind}.json"
    path.write_text(json.dumps(model.document))
    loaded = ScoreModel.load(path)
    scores = [loaded.score(row.features) for row in rows(100, 2012)]
    batched = batch_predictions(loaded, rows(100, 2012))
    assert [p.expected_r for p in batched] == pytest.approx([p.expected_r for p in scores], abs=1e-9)
    assert [p.score for p in batched] == pytest.approx([p.score_0_100 for p in scores], abs=1e-9)
    assert all(0 <= score.score_0_100 <= 100 for score in scores)
    assert sum(score.expected_r for score in scores) > 0
    assert audit_invariance(loaded, AnalysisConfig())


def test_purged_labels_and_transfer_pairs_never_enter_training() -> None:
    train_rows = rows(300, 2010) + rows(100, 2011)
    boundary = datetime(2011, 1, 1, tzinfo=UTC)
    crossing = Opportunity(boundary - timedelta(hours=30), boundary + timedelta(hours=6), "EURUSD", 100, 0, train_rows[0].features)
    transfer = Opportunity(boundary - timedelta(days=100), boundary - timedelta(days=99), "AUDUSD", 100, 0, train_rows[0].features)
    train, calibration = purged_split(train_rows + [crossing, transfer], datetime(2012, 1, 1, tzinfo=UTC), timedelta(hours=24), {"EURUSD"})
    assert crossing not in train and transfer not in train
    assert all(row.exit < boundary - timedelta(hours=24) for row in train)
    assert all(row.exit < datetime(2012, 1, 1, tzinfo=UTC) - timedelta(hours=24) for row in calibration)
    model = fit_model("bucket", train, calibration, "test", ScoringConfig())
    predictions = transfer_predictions([transfer], {2010: model}, {"AUDUSD"})
    assert len(predictions) == 1 and predictions[0].opportunity.pair == "AUDUSD"


def test_constant_inverted_and_missing_evidence_cannot_pass_scorecard() -> None:
    dataset = rows(300, 2019)
    constant = [Prediction(row, 0.03, 50) for row in dataset]
    card = scorecard_period(constant, ScoringConfig(), {"EURUSD", "GBPUSD", "USDJPY"}, True, 42, draws=100)
    assert not card["T1"]["passed"] and not card["T5"]["passed"] and not card["T6"]["passed"]
    inverted = [Prediction(row, -row.net_r, 100 * (1 - row.features["h1_range_position"])) for row in dataset]
    card = scorecard_period(inverted, ScoringConfig(), {"EURUSD", "GBPUSD", "USDJPY"}, True, 42, draws=100)
    assert card["T1"]["spearman"] < 0 and not card["T1"]["passed"]
    assert not card["T3"]["passed"]


def test_dataset_provenance_tampering_is_rejected(tmp_path: Path) -> None:
    dataset = rows(1)[0]
    record = {"decision_time": dataset.decision.isoformat(), "exit_time": dataset.exit.isoformat(),
              "pair": "EURUSD", "setup": "test", "net_r": dataset.net_r, "cost_r": dataset.cost_r,
              "net_r_2x_cost": dataset.net_r - dataset.cost_r, **dataset.features}
    path = tmp_path / "dataset.csv"
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(record))
        writer.writeheader()
        writer.writerow(record)
    metadata = {"schema": FEATURE_SCHEMA, "entry_rule": "decision-close", "strategy_signature": "test",
                "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    path.with_suffix(".metadata.json").write_text(json.dumps(metadata))
    assert len(read_datasets([path])[0]) == 1
    path.write_text(path.read_text() + "tampering")
    with pytest.raises(ValueError, match="SHA-256"):
        read_datasets([path])


def test_sizing_drawdown_includes_open_trade_paths_and_requires_them() -> None:
    decision = datetime(2019, 1, 1, tzinfo=UTC)
    data = []
    for index, (mu, outcome, adverse) in enumerate(((0.25, 2, -0.1), (-0.5, -1, -1), (0.01, 1, -0.8))):
        opened = decision + timedelta(days=index * 3)
        exit_ = opened + timedelta(days=2)
        path = ((opened, 0), (opened + timedelta(days=1), adverse), (exit_, outcome))
        row = Opportunity(opened, exit_, "EURUSD", outcome, 0, {}, path)
        data.append(Prediction(row, mu, 50))
    result = equity_comparison(data, ScoringConfig())
    assert result["passed"] and result["equity_paths_complete"]
    assert result["flat"]["max_drawdown"] >= 0.08  # Third trade dips -0.8R before winning.
    assert result["dynamic"]["max_drawdown"] < result["flat"]["max_drawdown"]
    from dataclasses import replace
    incomplete = [replace(p, opportunity=replace(p.opportunity, r_path=())) for p in data]
    assert not equity_comparison(incomplete, ScoringConfig())["passed"]


def test_training_command_writes_hash_checked_shadow_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import train_setup_score

    from forex.config import load_config
    from forex.scoring import strategy_signature

    config = load_config(Path("config.yaml"))
    dataset = rows(200, 2010) + rows(100, 2011) + rows(100, 2012) + rows(100, 2020) + rows(100, 2021)
    path = tmp_path / "unit-fixture.csv"
    records = [{"decision_time": r.decision.isoformat(), "exit_time": r.exit.isoformat(),
                "pair": r.pair, "setup": "unit-test-only", "net_r": r.net_r, "cost_r": r.cost_r,
                "net_r_2x_cost": r.net_r - r.cost_r, **r.features} for r in dataset]
    with path.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    path.with_suffix(".metadata.json").write_text(json.dumps({
        "schema": FEATURE_SCHEMA, "entry_rule": "decision-close", "strategy_signature": strategy_signature(config),
        "dataset_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "source": "synthetic unit fixture"}))
    destination = tmp_path / "model.json"
    monkeypatch.setattr(sys, "argv", ["train_setup_score.py", "--dataset", str(path), "--as-of", "2022-01-01", "--out", str(destination)])
    assert train_setup_score.main() == 0
    model = ScoreModel.load(destination)
    assert model.document["status"] == "shadow_only"
    assert not model.document["scorecard"]["passed"]
    assert len(json.loads(destination.with_suffix(".candidates.json").read_text())) == 4
    with pytest.raises(ValueError, match="7/7"):
        model.require_acceptance(config)


def test_export_includes_rejected_opportunities_and_excludes_unresolved_labels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import export_setup_dataset
    from causal_replay import Hour

    start = datetime(2020, 1, 1, tzinfo=UTC)
    features = rows(1)[0].features
    hours = [Hour(start, 100, 100.5, 99.5, 100, 1, 99, 1, False, True, "unit-test", features),
             Hour(start + timedelta(hours=1), 100, 111, 100, 110, 1, 99, 1, False),
             Hour(start + timedelta(hours=2), 110, 111, 109, 110, 1, 109, 1, True, True, "unit-test", features)]
    monkeypatch.setattr(export_setup_dataset, "analyse_pair", lambda *args, **kwargs: ("EURUSD", hours))
    monkeypatch.setattr(export_setup_dataset, "require_data", lambda *args: None)
    destination = tmp_path / "dataset.csv"
    monkeypatch.setattr(sys, "argv", ["export_setup_dataset.py", "--research-database", "unit-fixture-only", "--symbols", "EURUSD",
                                     "--start", "2020-01-01", "--end", "2021-01-01", "--cost-pips", "EURUSD=0.9",
                                     "--cost-provenance", "unit fixture", "--out", str(destination)])
    assert export_setup_dataset.main() == 0
    metadata = json.loads(destination.with_suffix(".metadata.json").read_text())
    assert metadata["rows"] == metadata["censored"] == 1
    opportunities, _ = read_datasets([destination])
    assert len(opportunities) == 1 and opportunities[0].r_path
    assert opportunities[0].net_r == pytest.approx(10 - 0.9 * 0.0001)
    assert opportunities[0].features == features
