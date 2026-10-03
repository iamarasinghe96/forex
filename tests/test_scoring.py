from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
from test_analysis import START, candles, compact_config
from test_learning import runtime_fixture
from test_risk import NOW, POLICY, account, candidate, spec

from forex.analysis import analyse_market
from forex.config import ScoringConfig, load_config
from forex.domain import Timeframe
from forex.errors import OperatorError
from forex.journal import JournalStore
from forex.learning import candidate_keys, strategy_version
from forex.notifications import NotificationWorker
from forex.risk import (
    DailyRiskState,
    DecisionStatus,
    PortfolioRiskState,
    RiskBlockReason,
    decide_risk,
    risk_percent_for_score,
)
from forex.scoring import (
    FEATURE_SCHEMA,
    PERIODS,
    TRANSFER_PAIRS,
    ScoreModel,
    ScoreResult,
    SetupFeatures,
    model_hash,
    strategy_signature,
)


def write_model(path: Path, config=None, *, accepted: bool = False, mu: float = 0.03) -> ScoreModel:
    config = config or load_config(Path("config.yaml"))
    tests = {f"T{i}": {"passed": accepted} for i in range(1, 8)}
    document = {"schema": FEATURE_SCHEMA, "kind": "bucket", "features": ["h1_range_position"],
                "scaler": {"mean": [0], "scale": [1]},
                "model": {"edges": [[0.3, 0.6]], "prior_mean": mu, "cells": {}},
                "calibration": {"x": [-1, 1], "y": [-1, 1]}, "training_distribution": [-0.4, -0.1, 0, 0.1, 0.3],
                "strategy_signature": strategy_signature(config),
                "sizing_config": config.scoring.model_dump(mode="json", exclude={"enabled", "shadow", "model_path"}),
                "scorecard": {"tests": tests, "periods": {p: tests for p in PERIODS},
                              "transfer_periods": {p: tests for p in PERIODS}, "transfer_pairs": list(TRANSFER_PAIRS)}}
    document["sha256"] = model_hash(document)
    path.write_text(json.dumps(document), encoding="utf-8")
    return ScoreModel.load(path)


def test_features_and_score_are_scale_invariant_and_ignore_future_bars(tmp_path: Path) -> None:
    config = compact_config()
    h1 = candles(Timeframe.H1, [1.1 + i * 0.00003 + math.sin(i / 5) * 0.002 for i in range(400)])
    h4 = candles(Timeframe.H4, [1.1 + i * 0.0001 + math.sin(i / 7) * 0.004 for i in range(150)])
    now = START + timedelta(hours=360)
    model = write_model(tmp_path / "model.json")
    def score(h1, h4):
        features = SetupFeatures.from_snapshot(analyse_market("EURUSD", h1, h4, now, config).snapshot)
        return features, model.score(features)
    original, result = score(h1, h4)
    def changed(bars, future_only=False):
        return [replace(c, open=c.open * 2, high=c.high * 2, low=c.low * 2, close=c.close * 2)
                if not future_only or c.timestamp_utc + c.timeframe.duration > now else c for c in bars]
    for alternative in (score(changed(h1), changed(h4)), score(changed(h1, True), changed(h4, True))):
        assert alternative[0].values == pytest.approx(original.values)
        assert alternative[1] == result
    assert not {"h1_atr", "h1_rolling_high", "h1_rolling_low", "balance"} & set(original.values)


def test_model_hash_forbidden_features_and_midrank(tmp_path: Path) -> None:
    path = tmp_path / "model.json"
    model = write_model(path)
    document = json.loads(path.read_text())
    document["model"]["prior_mean"] = 0.9
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="SHA-256"):
        ScoreModel.load(path)
    document["features"] = ["h1_atr"]
    document["sha256"] = model_hash(document)
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="forbidden"):
        ScoreModel.load(path)
    document = dict(model.document)
    mu = model.score({"h1_range_position": 0.5}).expected_r
    document["training_distribution"] = [mu] * 100
    assert ScoreModel(document).score({"h1_range_position": 0.5}).score_0_100 == 50


def test_kelly_mapping_skip_units_caps_and_monotonicity() -> None:
    config = ScoringConfig()
    assert risk_percent_for_score(0.03, config) == Decimal("0.25") * Decimal("0.03") / Decimal("1.1")
    assert risk_percent_for_score(0.20, config) == Decimal("0.25") * Decimal("0.20") / Decimal("1.1")
    assert risk_percent_for_score(10, config) == Decimal("0.05")
    assert risk_percent_for_score(0.00001, config) == Decimal("0.0025")
    assert risk_percent_for_score(0, config) == risk_percent_for_score(-1, config) == 0
    risks = [risk_percent_for_score(i / 100, config) for i in range(-100, 101)]
    assert risks == sorted(risks)
    with pytest.raises(ValueError, match="finite"):
        risk_percent_for_score(float("nan"), config)
    with pytest.raises(ValueError):
        ScoringConfig(min_risk_percent=3, max_risk_percent=2)


def test_dynamic_risk_replaces_conviction_but_preserves_circuit_and_leverage() -> None:
    score = ScoreResult(80, 0.03, "Q5", "test-hash")
    config = ScoringConfig(enabled=True, shadow=False)
    args = (candidate(uncertainty=0.99), account(), spec(), Decimal("1.1"), Decimal("1.09"),
            None, PortfolioRiskState(()), DailyRiskState("day", Decimal(10000), Decimal(10000)), POLICY)
    risk = decide_risk(*args, setup_score=score, scoring=config)
    assert risk.status is DecisionStatus.ELIGIBLE
    assert risk.tier.risk_percent == risk_percent_for_score(0.03, config)
    assert decide_risk(*args, setup_score=replace(score, expected_r=0), scoring=config).reasons == (RiskBlockReason.SETUP_SCORE_NOT_POSITIVE,)
    with pytest.raises(ValueError, match="validated model"):
        decide_risk(*args, scoring=config)
    halted = list(args)
    halted[7] = DailyRiskState("day", Decimal(10000), Decimal(8000))
    assert decide_risk(*halted, setup_score=score, scoring=config).status is DecisionStatus.HALT_FLATTEN_REQUIRED
    leveraged = list(args)
    leveraged[1] = replace(account(), leverage=31)
    assert RiskBlockReason.INVALID_LEVERAGE in decide_risk(*leveraged, setup_score=score, scoring=config).reasons


def test_shadow_logs_model_features_and_keeps_flat_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, _, _ = runtime_fixture(tmp_path, monkeypatch)
    runtime.config.scoring.model_path = tmp_path / "model.json"
    model = write_model(runtime.config.scoring.model_path, runtime.config, mu=-0.2)
    runtime.load_score_model(NOW)
    runtime.cycle()
    events = runtime.journal.events(limit=500)
    candidate_event = next(e for e in events if e.kind == "candidate")
    scoring = candidate_event.payload["setup_score"]
    assert scoring["shadow"] and scoring["expected_r"] == pytest.approx(-0.2)
    assert scoring["model_sha256"] == model.sha256 and scoring["features"]
    risk = next(e for e in events if e.kind == "risk_decision").payload["risk"]
    assert Decimal(risk["tier"]["risk_percent"]) == Decimal("0.05")
    assert "score:Q2" in candidate_keys("EURUSD", {**candidate_event.payload["candidate"], "setup_score": scoring})
    version = strategy_version(runtime.config)
    write_model(runtime.config.scoring.model_path, runtime.config, mu=0.2)
    assert version != strategy_version(runtime.config)


def test_activation_requires_all_tests_matching_settings_and_four_weeks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, _, _ = runtime_fixture(tmp_path, monkeypatch)
    config = runtime.config
    config.scoring.model_path = tmp_path / "model.json"
    model = write_model(config.scoring.model_path, config)
    config.scoring.enabled, config.scoring.shadow = True, False
    with pytest.raises(OperatorError, match="7/7"):
        runtime.load_score_model(NOW)
    model = write_model(config.scoring.model_path, config, accepted=True)
    with pytest.raises(OperatorError, match="four weeks"):
        runtime.load_score_model(NOW)
    for offset in (28, 0):
        runtime.journal.append("PAPER", "candidate", f"shadow-{offset}",
                               {"setup_score": {"shadow": True, "status": "available", "model_sha256": model.sha256,
                                                "strategy_signature": strategy_signature(config)}}, NOW - timedelta(days=offset))
    runtime.load_score_model(NOW)
    assert runtime.score_model is not None
    config.scoring.kelly_fraction = 0.5
    with pytest.raises(OperatorError, match="different sizing"):
        runtime.load_score_model(NOW)
    config.scoring.kelly_fraction = 0.25
    config.paper.atr_trailing_multiple = 2
    with pytest.raises(OperatorError, match="exit rules"):
        runtime.load_score_model(NOW)


def test_missing_shadow_model_preserves_candidate_and_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, _, _ = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()
    events = runtime.journal.events(limit=500)
    assert next(e for e in events if e.kind == "candidate").payload["setup_score"]["status"] == "unavailable"
    assert next(e for e in events if e.kind == "risk_decision").payload["risk"]["tier"]["risk_percent"] == "0.05"


def test_score_band_survives_trade_provenance_and_alerts(tmp_path: Path) -> None:
    journal = JournalStore(tmp_path / "journal.sqlite3")
    payload = {"symbol": "EURUSD", "decision_provenance": {
        "candidate": {"setup_score": {"status": "available", "score_0_100": 82}},
        "context_review": {"review": {"plan": {"actual_risk_percent": "0.031"}}}}}
    journal.append("PAPER", "trade_opened", "trade-1", payload, NOW)
    alerter = Mock()
    NotificationWorker(journal, alerter).once()
    assert "score 82/100, risk 3.1%" in alerter.send.call_args.args[0]


def test_period_acceptance_cannot_be_faked_by_overall_pass(tmp_path: Path) -> None:
    config = load_config(Path("config.yaml"))
    model = write_model(tmp_path / "model.json", config, accepted=True)
    document = json.loads(json.dumps(model.document))
    document["scorecard"]["transfer_periods"][PERIODS[0]]["T1"]["passed"] = False
    with pytest.raises(ValueError, match="both periods"):
        ScoreModel(document).require_acceptance(config)


def test_shadow_score_buckets_cannot_change_existing_learning_sizing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_costs_and_versions import facts

    runtime, _, _ = runtime_fixture(tmp_path, monkeypatch)
    baseline_version = strategy_version(runtime.config, "")
    # Historical baseline reductions remain active when a shadow model is introduced.
    for i in range(40):
        runtime.learning.record_trade(facts(f"baseline-{i}", -1, baseline_version), NOW)
    runtime.config.scoring.model_path = tmp_path / "model.json"
    write_model(runtime.config.scoring.model_path, runtime.config, mu=-0.2)
    runtime.load_score_model(NOW)
    runtime.cycle()
    events = runtime.journal.events(limit=500)
    sizing = next(e for e in events if e.kind == "learning_decision").payload["sizing"]
    assert sizing["factor"] == 0.25 and all(not k.startswith("score:") for k in sizing["buckets"])
    scored_candidate = next(e for e in events if e.kind == "candidate")
    assert scored_candidate.payload["strategy_version"] != baseline_version
    assert scored_candidate.payload["sizing_version"] == baseline_version
    # Logged score-band losses may be studied, but do not enter the shadow sizing key list.
    runtime.learning.record_trade(replace(facts("shadow-1", -1, scored_candidate.payload["strategy_version"]),
                                         score_band="Q1", sizing_version=baseline_version), NOW)
    assert runtime.learning.scores(20, baseline_version, sizing=True)["all"].trades == 41
    assert runtime.learning.scores(20, scored_candidate.payload["strategy_version"])["score:Q1"].trades == 1
