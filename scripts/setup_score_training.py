"""Offline setup-model fitting and purged chronological acceptance tests.

Training dependencies are optional; the runtime JSON scorer uses only the standard library.
All model choices/constraints are fixed here before looking at confirmation pairs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import Ridge
from sklearn.neighbors import KNeighborsRegressor
from sklearn.preprocessing import StandardScaler

from forex.analysis import analyse_market
from forex.config import AnalysisConfig, ScoringConfig
from forex.domain import Candle, Timeframe
from forex.scoring import (
    FEATURE_SCHEMA,
    PERIODS,
    ScoreModel,
    SetupFeatures,
    allowed_feature,
    model_hash,
)

BUCKET_FEATURES = ("h4_directional_efficiency", "h1_range_position", "h1_volatility_rank", "style_swing")
MODEL_ORDER = ("bucket", "ridge", "knn", "boosted")


@dataclass(frozen=True)
class Opportunity:
    decision: datetime
    exit: datetime
    pair: str
    net_r: float
    cost_r: float
    features: dict[str, float]
    r_path: tuple[tuple[datetime, float], ...] = ()


@dataclass(frozen=True)
class Prediction:
    opportunity: Opportunity
    expected_r: float
    score: float


def read_datasets(paths: list[Path]) -> tuple[list[Opportunity], dict[str, Any]]:
    csv.field_size_limit(100_000_000)  # Long-lived opportunities can have large hourly R paths.
    rows: list[Opportunity] = []
    sources = []
    signature = None
    feature_names = None
    seen = set()
    for path in paths:
        metadata = json.loads(path.with_suffix(".metadata.json").read_text(encoding="utf-8"))
        if metadata["dataset_sha256"] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError(f"Dataset SHA-256 mismatch: {path}")
        if metadata["schema"] != FEATURE_SCHEMA or metadata["entry_rule"] != "decision-close":
            raise ValueError("Unsupported dataset features or entry rule")
        if signature is not None and signature != metadata["strategy_signature"]:
            raise ValueError("Datasets use different analysis/exit rules; export them again")
        signature = metadata["strategy_signature"]
        sources.append({"sha256": metadata["dataset_sha256"], "metadata": metadata})
        with path.open(newline="", encoding="utf-8") as source:
            for record in csv.DictReader(source):
                names = set(record) - {"decision_time", "exit_time", "pair", "setup", "net_r", "cost_r", "net_r_2x_cost", "r_path_json"}
                if not names or any(not allowed_feature(name) for name in names):
                    raise ValueError("Dataset contains forbidden or missing features")
                if feature_names is not None and names != feature_names:
                    raise ValueError("Dataset rows have different feature schemas")
                feature_names = names
                decision, exit_ = datetime.fromisoformat(record["decision_time"]), datetime.fromisoformat(record["exit_time"])
                if decision.utcoffset() != timedelta(0) or exit_.utcoffset() != timedelta(0) or exit_ <= decision:
                    raise ValueError("Dataset requires UTC timestamps and an exit after the decision")
                pair = record["pair"].upper()
                identity = (decision, pair)
                if identity in seen:
                    raise ValueError("Duplicate opportunity across datasets")
                seen.add(identity)
                net_r, cost_r = float(record["net_r"]), float(record["cost_r"])
                features = {key: float(record[key]) for key in names}
                if not all(math.isfinite(v) for v in [net_r, cost_r, *features.values()]) or cost_r < 0:
                    raise ValueError("Dataset requires finite features/outcomes and nonnegative costs")
                if not math.isclose(float(record["net_r_2x_cost"]), net_r - cost_r, abs_tol=1e-9):
                    raise ValueError("Dataset cost-stress label is inconsistent")
                path_data = json.loads(record.get("r_path_json") or "[]")
                r_path = tuple((datetime.fromisoformat(t), float(r)) for t, r in path_data)
                if r_path and (r_path[0][0] != decision or r_path[-1][0] != exit_ or
                               not math.isclose(r_path[-1][1], net_r, abs_tol=1e-9) or
                               not math.isclose(r_path[0][1], -cost_r, abs_tol=1e-9) or
                               any(t.utcoffset() != timedelta(0) or not math.isfinite(r) for t, r in r_path) or
                               any(b[0] <= a[0] for a, b in pairwise(r_path))):
                    raise ValueError("Dataset equity path is inconsistent with timestamps, costs or outcome")
                rows.append(Opportunity(decision, exit_, pair, net_r, cost_r, features, r_path))
    if not rows:
        raise ValueError("No completed setup opportunities")
    return sorted(rows, key=lambda row: (row.decision, row.pair)), {"sources": sources, "strategy_signature": signature}


def fit_model(kind: str, training: list[Opportunity], calibration: list[Opportunity],
              signature: str, sizing: ScoringConfig) -> ScoreModel:
    if len(training) < 100 or len(calibration) < 50:
        raise ValueError("A fold needs at least 100 fitting and 50 disjoint calibration opportunities")
    features = list(BUCKET_FEATURES) if kind == "bucket" else sorted(training[0].features)
    x = np.array([[row.features[key] for key in features] for row in training])
    y = np.array([row.net_r for row in training])
    scaler = StandardScaler().fit(x)
    standardized = scaler.transform(x)
    if kind == "bucket":
        edges = np.quantile(x, [1 / 3, 2 / 3], axis=0).T.tolist()
        groups = defaultdict(list)
        for row, outcome in zip(x, y):
            cell = ",".join(str(np.searchsorted(edge, value, side="left")) for edge, value in zip(edges, row))
            groups[cell].append(float(outcome))
        prior = float(np.mean(y))
        model = {"edges": edges, "prior_mean": prior, "prior_count": 20,
                 "cells": {key: (sum(values) + 20 * prior) / (len(values) + 20) for key, values in groups.items()}}
    elif kind == "ridge":
        fitted = Ridge(alpha=10).fit(standardized, y)
        model = {"coefficients": fitted.coef_.tolist(), "intercept": float(fitted.intercept_), "alpha": 10}
    elif kind == "knn":
        k = min(50, len(training))
        model = {"k": k, "vectors": standardized.tolist(), "outcomes": y.tolist()}
    elif kind == "boosted":
        # Predeclared hypothesis: stronger H4 persistence cannot reduce predicted quality.
        constraints = [int(name == "h4_trend_strength") for name in features]
        fitted = HistGradientBoostingRegressor(max_iter=50, max_depth=2, min_samples_leaf=30,
                                               l2_regularization=10, monotonic_cst=constraints,
                                               early_stopping=False, random_state=20261003).fit(standardized, y)
        trees = []
        for iteration in fitted._predictors:
            nodes = iteration[0].nodes
            trees.append([{"leaf": bool(n["is_leaf"]), "value": float(n["value"]),
                           "feature": int(n["feature_idx"]), "threshold": float(n["num_threshold"]),
                           "left": int(n["left"]), "right": int(n["right"])} for n in nodes])
        model = {"baseline": float(fitted._baseline_prediction[0, 0]), "trees": trees,
                 "monotone_constraints": constraints}
    else:
        raise ValueError("Unknown setup model")
    document = {"schema": FEATURE_SCHEMA, "kind": kind, "features": features,
                "scaler": {"mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist()}, "model": model,
                "calibration": {"x": [0], "y": [0]}, "training_distribution": [0],
                "strategy_signature": signature,
                "sizing_config": sizing.model_dump(mode="json", exclude={"enabled", "shadow", "model_path"}),
                "training_window": {"fit_start": min(r.decision for r in training).isoformat(),
                                    "fit_last_label": max(r.exit for r in training).isoformat(),
                                    "calibration_start": min(r.decision for r in calibration).isoformat(),
                                    "calibration_last_label": max(r.exit for r in calibration).isoformat()}}
    portable = ScoreModel(document)
    predictions = batch_raw_predictions(portable, np.array([[r.features[k] for k in features] for r in calibration]))
    isotonic = IsotonicRegression(out_of_bounds="clip").fit(predictions, [r.net_r for r in calibration])
    document["calibration"] = {"x": isotonic.X_thresholds_.tolist(), "y": isotonic.y_thresholds_.tolist()}
    document["training_distribution"] = sorted(np.round(np.interp(batch_raw_predictions(portable, x),
                                                                  document["calibration"]["x"], document["calibration"]["y"]), 12).tolist())
    document["sha256"] = model_hash(document)
    portable.validate()
    # Verify portable tree/linear/analogue serialization against the training library.
    if kind == "boosted" and not np.allclose([portable.predict(row.tolist()) for row in x[:100]],
                                             fitted.predict(standardized[:100]), rtol=1e-9, atol=1e-9):
        raise ValueError("Portable boosted-tree predictions differ from training library")
    return portable


def batch_raw_predictions(model: ScoreModel, x: Any) -> Any:
    """Vectorized offline inference; avoid quadratic Python loops for analogue evaluation."""
    doc = model.document
    data = doc["model"]
    if doc["kind"] == "bucket":
        return np.array([model.predict(row.tolist()) for row in x])
    scaled = (x - np.array(doc["scaler"]["mean"])) / np.array(doc["scaler"]["scale"])
    if doc["kind"] == "ridge":
        return scaled @ np.array(data["coefficients"]) + data["intercept"]
    if doc["kind"] == "knn":
        analogues = KNeighborsRegressor(n_neighbors=data["k"]).fit(data["vectors"], data["outcomes"])
        return analogues.predict(scaled)
    predictions = np.full(len(x), data["baseline"], dtype=float)
    for tree in data["trees"]:
        for index, node in enumerate(tree):
            if not node["leaf"]:
                continue
            mask = np.ones(len(x), dtype=bool)
            child = index
            while child:
                parent = next(i for i, n in enumerate(tree) if not n["leaf"] and child in (n["left"], n["right"]))
                split = scaled[:, tree[parent]["feature"]] <= tree[parent]["threshold"]
                mask &= split if tree[parent]["left"] == child else ~split
                child = parent
            predictions[mask] += node["value"]
    return predictions


def batch_predictions(model: ScoreModel, rows: list[Opportunity]) -> list[Prediction]:
    if not rows:
        return []
    doc = model.document
    x = np.array([[row.features[key] for key in doc["features"]] for row in rows])
    mus = np.round(np.interp(batch_raw_predictions(model, x), doc["calibration"]["x"], doc["calibration"]["y"]), 12)
    reference = np.array(doc["training_distribution"])
    scores = 50 * (np.searchsorted(reference, mus, side="left") + np.searchsorted(reference, mus, side="right")) / len(reference)
    return [Prediction(row, float(mu), float(score)) for row, mu, score in zip(rows, mus, scores)]


def purged_split(rows: list[Opportunity], test_start: datetime, embargo: timedelta,
                 training_pairs: set[str]) -> tuple[list[Opportunity], list[Opportunity]]:
    validation_start = test_start.replace(year=test_start.year - 1)
    train = [r for r in rows if r.pair in training_pairs and r.decision < validation_start - embargo
             and r.exit < validation_start - embargo]
    calibration = [r for r in rows if r.pair in training_pairs and validation_start <= r.decision < test_start - embargo
                   and r.exit < test_start - embargo]
    return train, calibration


def walk_forward(rows: list[Opportunity], kind: str, training_pairs: set[str], signature: str,
                 sizing: ScoringConfig, embargo: timedelta) -> tuple[list[Prediction], dict[int, ScoreModel], list[dict[str, Any]]]:
    predictions, models, folds = [], {}, []
    for year in range(2012, 2027):
        start, end = datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC)
        train, calibration = purged_split(rows, start, embargo, training_pairs)
        test = [r for r in rows if r.pair in training_pairs and start <= r.decision < end and r.exit < end]
        fold = {"year": year, "fit_rows": len(train), "calibration_rows": len(calibration), "test_rows": len(test)}
        if len(train) < 100 or len(calibration) < 50 or not test:
            fold["status"] = "insufficient_data"
        else:
            model = fit_model(kind, train, calibration, signature, sizing)
            models[year] = model
            predictions.extend(batch_predictions(model, test))
            fold.update(status="out_of_sample", training_window=model.document["training_window"])
        folds.append(fold)
    return predictions, models, folds


def transfer_predictions(rows: list[Opportunity], models: dict[int, ScoreModel], pairs: set[str]) -> list[Prediction]:
    grouped = defaultdict(list)
    for row in rows:
        year = row.decision.year
        if row.pair not in pairs or year not in models or row.exit >= datetime(year + 1, 1, 1, tzinfo=UTC):
            continue
        grouped[year].append(row)
    return [p for year, group in sorted(grouped.items()) for p in batch_predictions(models[year], group)]


def block_means(predictions: list[Prediction], rng: Any, draws: int) -> Any:
    # Pair/month blocks retain overlapping outcomes rather than treating every hour as independent.
    groups = defaultdict(list)
    for p in predictions:
        r = p.opportunity
        groups[(r.pair, r.decision.year, r.decision.month)].append(r.net_r)
    if len(groups) < 2:
        return None
    totals = np.array([sum(v) for v in groups.values()])
    counts = np.array([len(v) for v in groups.values()])
    sampled = rng.integers(0, len(totals), (draws, len(totals)))
    return totals[sampled].sum(axis=1) / counts[sampled].sum(axis=1)


def block_mean_ci(predictions: list[Prediction], rng: Any, draws: int) -> tuple[float, float] | None:
    means = block_means(predictions, rng, draws)
    return tuple(float(v) for v in np.quantile(means, [0.025, 0.975])) if means is not None else None


def quintiles(predictions: list[Prediction]) -> list[list[Prediction]]:
    values = np.array([p.score for p in predictions])
    if len(values) < 50:
        return []
    edges = np.quantile(values, [0.2, 0.4, 0.6, 0.8])
    if len(set(edges)) != 4:
        return []  # Never split equal scores using the outcome or timestamp to invent separation.
    groups = [[] for _ in range(5)]
    for p in predictions:
        groups[int(np.searchsorted(edges, p.score, side="left"))].append(p)
    return groups if all(len(group) >= 5 for group in groups) else []


def monotonic_test(predictions: list[Prediction], rng: Any, draws: int) -> dict[str, Any]:
    groups = quintiles(predictions)
    if not groups:
        return {"passed": False, "reason": "Need five nonempty score quintiles with distinct boundaries"}
    means = [float(np.mean([p.opportunity.net_r for p in g])) for g in groups]
    # Spearman ranks with ties averaged.
    ranks = [sum(v < m for v in means) + (sum(v == m for v in means) - 1) / 2 for m in means]
    rho = float(np.corrcoef(range(5), ranks)[0, 1]) if len(set(ranks)) > 1 else 0.0
    bottom, top = block_means(groups[0], rng, draws), block_means(groups[-1], rng, draws)
    interval = [float(v) for v in np.quantile(top - bottom, [0.025, 0.975])] if top is not None and bottom is not None else None
    return {"passed": bool(rho > 0 and interval and interval[0] > 0), "spearman": rho,
            "means_r": means, "spread_r": means[-1] - means[0], "spread_ci95": interval}


def equity_comparison(predictions: list[Prediction], sizing: ScoringConfig) -> dict[str, Any]:
    from forex.risk import risk_percent_for_score
    # Same executable opportunities for both sizes; one position per pair and <=4 positions.
    chosen, held = [], {}
    for p in sorted(predictions, key=lambda p: (p.opportunity.decision, p.opportunity.pair)):
        r = p.opportunity
        held = {pair: exit_ for pair, exit_ in held.items() if exit_ > r.decision}
        if r.pair in held or len(held) >= 4:
            continue
        held[r.pair] = r.exit
        chosen.append(p)

    def curve(dynamic: bool) -> dict[str, float]:
        balance, peak, drawdown = 1.0, 1.0, 0.0
        events = defaultdict(list)
        for index, p in enumerate(chosen):
            r = p.opportunity
            events[r.decision].append((2, index, -r.cost_r))
            for time, mark_r in r.r_path[1:-1]:
                events[time].append((1, index, mark_r))
            events[r.exit].append((0, index, r.net_r))
        active = {}
        for _, changes in sorted(events.items()):
            for kind, index, mark_r in sorted(changes):
                if kind == 2:
                    p = chosen[index]
                    fraction = float(risk_percent_for_score(p.expected_r, sizing)) if dynamic else sizing.max_risk_percent / 100
                    active[index] = (balance * fraction, mark_r)
                elif kind == 1:
                    amount, _ = active[index]
                    active[index] = (amount, mark_r)
                else:
                    amount, _ = active.pop(index)
                    balance += amount * mark_r
            equity = balance + sum(amount * mark_r for amount, mark_r in active.values())
            peak = max(peak, equity)
            drawdown = max(drawdown, 1 - equity / peak)
            if equity <= 0 or balance <= 0:
                return {"log_growth": -1e9, "max_drawdown": 1.0}
        return {"log_growth": math.log(balance) if balance > 0 else -1e9, "max_drawdown": min(1.0, drawdown)}

    dynamic, flat = curve(True), curve(False)
    paths_complete = bool(chosen) and all(p.opportunity.r_path for p in chosen)
    return {"passed": bool(paths_complete and dynamic["log_growth"] > flat["log_growth"]
                           and dynamic["max_drawdown"] < flat["max_drawdown"]),
            "dynamic": dynamic, "flat": flat, "same_opportunities": len(chosen),
            "equity_paths_complete": paths_complete,
            "drawdown_basis": "hourly mark-to-market with net exit fills" if paths_complete else "incomplete paths; T4 cannot pass"}


def scorecard_period(predictions: list[Prediction], sizing: ScoringConfig, expected_pairs: set[str],
                     t7: bool, seed: int, draws: int = 1000) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    t1 = monotonic_test(predictions, rng, draws)
    groups = quintiles(predictions)
    top_stress = float(np.mean([p.opportunity.net_r - p.opportunity.cost_r for p in groups[-1]])) if groups else None
    stable = {pair: monotonic_test([p for p in predictions if p.opportunity.pair == pair], rng, draws)
              for pair in sorted(expected_pairs)}
    t3 = sum(result["passed"] for result in stable.values()) >= (2 if len(expected_pairs) == 3 else math.ceil(2 * len(expected_pairs) / 3))
    pvalue = 1.0
    if groups:
        outcomes = np.array([p.opportunity.net_r for p in predictions])
        top_ids = {id(p) for p in groups[-1]}
        bottom_ids = {id(p) for p in groups[0]}
        top_mask = np.array([id(p) in top_ids for p in predictions])
        bottom_mask = np.array([id(p) in bottom_ids for p in predictions])
        real_spread = float(outcomes[top_mask].mean() - outcomes[bottom_mask].mean())
        exceed = 0
        for _ in range(1000):
            shuffled = rng.permutation(outcomes)
            exceed += shuffled[top_mask].mean() - shuffled[bottom_mask].mean() >= real_spread
        pvalue = (1 + exceed) / 1001
    deciles = []
    if len(predictions) >= 100:
        edges = np.quantile([p.score for p in predictions], np.arange(0.1, 1, 0.1))
        if len(set(edges)) == 9:
            for index in range(10):
                group = [p for p in predictions if int(np.searchsorted(edges, p.score, side="left")) == index]
                interval = block_mean_ci(group, rng, draws)
                predicted = float(np.mean([p.expected_r for p in group])) if group else None
                deciles.append({"n": len(group), "predicted_r": predicted, "realized_ci95": interval,
                                "passed": bool(interval and predicted is not None and interval[0] <= predicted <= interval[1])})
    return {"T1": t1, "T2": {"passed": bool(top_stress is not None and top_stress > 0), "top_net_r_2x_cost": top_stress},
            "T3": {"passed": bool(t1["passed"] and t3), "pairs": stable},
            "T4": equity_comparison(predictions, sizing), "T5": {"passed": bool(pvalue < 0.05), "permutations": 1000, "p_value": pvalue},
            "T6": {"passed": sum(d["passed"] for d in deciles) >= 8, "deciles": deciles},
            "T7": {"passed": t7, "basis": "real analysis on deterministic unit fixtures; future-bar mutation and x2 prices"},
            "opportunities": len(predictions), "observed_pairs": sorted({p.opportunity.pair for p in predictions})}


def audit_invariance(model: ScoreModel, config: AnalysisConfig) -> bool:
    # Deterministic unit fixtures only, never exported as market history or performance evidence.
    start = datetime(2000, 1, 1, tzinfo=UTC)
    streams = {}
    size = max(config.ema_context, config.volatility_window, max(config.return_horizons)) * 5 + 200
    for frame in Timeframe:
        bars = []
        for i in range(size):
            price = 1.1 + i * 0.00002 + math.sin(i / 9) * 0.002
            bars.append(Candle.from_values("EURUSD", frame, start + i * frame.duration,
                                          price, price + 0.001, price - 0.001, price + 0.0001, 100, 0, 0))
        streams[frame] = bars
    now = streams[Timeframe.H1][-20].timestamp_utc
    def evaluate(values: dict[Timeframe, list[Candle]]) -> tuple[SetupFeatures, Any]:
        snapshot = analyse_market("EURUSD", values[Timeframe.H1], values[Timeframe.H4], now, config).snapshot
        features = SetupFeatures.from_snapshot(snapshot)
        return features, model.score(features)
    original_features, original = evaluate(streams)
    mutated = {frame: [replace(c, open=c.open * 10, high=c.high * 10, low=c.low * 10, close=c.close * 10)
                       if c.timestamp_utc + c.timeframe.duration > now else c for c in bars]
               for frame, bars in streams.items()}
    scaled = {frame: [replace(c, open=c.open * 2, high=c.high * 2, low=c.low * 2, close=c.close * 2) for c in bars]
              for frame, bars in streams.items()}
    for values in (mutated, scaled):
        features, score = evaluate(values)
        if any(not math.isclose(v, features.values[key], rel_tol=1e-9, abs_tol=1e-9) for key, v in original_features.values.items()):
            return False
        if not math.isclose(score.expected_r, original.expected_r, abs_tol=1e-9) or not math.isclose(score.score_0_100, original.score_0_100, abs_tol=1e-9):
            return False
    return True


def aggregate_card(periods: dict[str, Any], transfer: dict[str, Any], pairs: set[str]) -> dict[str, Any]:
    tests = {f"T{i}": {"passed": all(periods[p][f"T{i}"]["passed"] and transfer.get(p, {}).get(f"T{i}", {}).get("passed", False)
                                     for p in PERIODS)} for i in range(1, 8)}
    count = sum(value["passed"] for value in tests.values())
    return {"tests": tests, "periods": periods, "transfer_periods": transfer, "transfer_pairs": sorted(pairs),
            "passed": count == 7, "line": f"score-model v1: {count}/7 passed"}
