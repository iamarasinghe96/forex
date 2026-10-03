"""Scale-invariant setup features and portable, content-addressed scoring. No score-time I/O."""

from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from forex.analysis import AnalysisSnapshot, RegimeLabel
from forex.config import AppConfig

FEATURE_SCHEMA = "setup-features-v1"
PERIODS = ("2012-2018", "2019-2026")
TRANSFER_PAIRS = ("AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURJPY", "GBPJPY")
NORMALIZED = (
    "ema_fast_slow_atr", "ema_slope_atr", "distance_fast_atr", "distance_slow_atr",
    "directional_efficiency", "directional_follow_through", "breakout_high_atr",
    "breakout_low_atr", "range_position", "mean_zscore", "rsi", "volatility_rank",
    "range_expansion", "atr_normalized", "realised_volatility", "body_ratio",
    "upper_wick_ratio", "lower_wick_ratio",
)


@dataclass(frozen=True)
class SetupFeatures:
    values: Mapping[str, float]

    @classmethod
    def from_snapshot(cls, snapshot: AnalysisSnapshot) -> SetupFeatures:
        raw = snapshot.feature_snapshot
        values: dict[str, float] = {}
        for frame in ("h1", "h4"):
            for name in NORMALIZED:
                key = f"{frame}_{name}"
                if key in raw:
                    values[key] = float(raw[key])
            atr = float(raw[f"{frame}_atr"])
            if not math.isfinite(atr) or atr <= 0:
                raise ValueError("setup features require a positive finite ATR")
            values[f"{frame}_macd_histogram_atr"] = float(raw[f"{frame}_macd_histogram"]) / atr
            values[f"{frame}_range_height_atr"] = (float(raw[f"{frame}_rolling_high"]) - float(raw[f"{frame}_rolling_low"])) / atr
            # Existing returns are percentages, already scale invariant.
            for key, value in raw.items():
                if key.startswith(f"{frame}_return_"):
                    values[key] = float(value)
        values["atr_h1_h4_ratio"] = float(raw["h1_atr"]) / float(raw["h4_atr"])
        values["h4_trend_strength"] = snapshot.regime.trend_strength
        values["side_long"] = float(snapshot.direction is not None and snapshot.direction.value == "LONG")
        values["style_swing"] = float(snapshot.trade_style is not None and snapshot.trade_style.value == "SWING")
        for session in ("ASIA", "LONDON", "NEW_YORK", "OFF_SESSION"):
            values[f"session_{session.lower()}"] = float(session in snapshot.session_context)
        for day in range(7):
            values[f"weekday_{day}"] = float(snapshot.evaluation_time_utc.weekday() == day)
        for regime in RegimeLabel:
            values[f"regime_{regime.value.lower()}"] = float(snapshot.regime.label is regime)
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("setup features must be finite")
        return cls(MappingProxyType(values))


def allowed_feature(name: str) -> bool:
    for frame in ("h1", "h4"):
        if name in {f"{frame}_{key}" for key in (*NORMALIZED, "macd_histogram_atr", "range_height_atr")}:
            return True
        prefix = f"{frame}_return_"
        if name.startswith(prefix) and name[len(prefix):].isdigit():
            return int(name[len(prefix):]) > 0
    return name in {"atr_h1_h4_ratio", "h4_trend_strength", "side_long", "style_swing"} or name in {
        *(f"session_{s}" for s in ("asia", "london", "new_york", "off_session")),
        *(f"weekday_{d}" for d in range(7)), *(f"regime_{r.value.lower()}" for r in RegimeLabel),
    }


def model_hash(document: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def strategy_signature(config: AppConfig) -> str:
    """Bind outcomes to the exact analysis and paper exit rules, excluding risk sizing."""
    payload = {"analysis": config.analysis.model_dump(mode="json"),
               "target_r": config.paper.target_reward_risk or config.risk.minimum_reward_risk,
               "breakeven_r": 1.0, "trail_atr": config.paper.atr_trailing_multiple,
               "horizon_bars": 0, "entry_rule": "decision-close", "feature_schema": FEATURE_SCHEMA}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class ScoreResult:
    score_0_100: float
    expected_r: float
    band: str
    model_sha256: str


@dataclass(frozen=True)
class ScoreModel:
    document: Mapping[str, Any]

    @classmethod
    def load(cls, path: Path | str) -> ScoreModel:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        try:
            if not isinstance(document, dict) or document.get("sha256") != model_hash(document):
                raise ValueError("setup model SHA-256 mismatch")
            model = cls(document)
            model.validate()
        except (KeyError, TypeError, IndexError, AttributeError) as exc:
            raise ValueError("invalid setup model structure") from exc
        return model

    def validate(self) -> None:
        doc = self.document
        if doc.get("schema") != FEATURE_SCHEMA:
            raise ValueError("unsupported setup model feature schema")
        features = doc.get("features", [])
        if not features or len(set(features)) != len(features) or any(not allowed_feature(f) for f in features):
            raise ValueError("model contains missing, duplicate or forbidden price/account features")
        if doc.get("kind") not in {"bucket", "ridge", "knn", "boosted"}:
            raise ValueError("unsupported setup model kind")
        for key in ("mean", "scale"):
            if len(doc["scaler"][key]) != len(features):
                raise ValueError("invalid setup model scaler")
        if any(not math.isfinite(v) for key in ("mean", "scale") for v in doc["scaler"][key]):
            raise ValueError("nonfinite setup model scaler")
        if any(v <= 0 for v in doc["scaler"]["scale"]):
            raise ValueError("setup model scale must be positive")
        calibration = doc["calibration"]
        if not calibration["x"] or len(calibration["x"]) != len(calibration["y"]):
            raise ValueError("invalid setup calibration")
        if any(b <= a for a, b in zip(calibration["x"], calibration["x"][1:])) or any(
            b < a for a, b in zip(calibration["y"], calibration["y"][1:])
        ):
            raise ValueError("setup calibration must be monotone")
        distribution = doc["training_distribution"]
        if not distribution or distribution != sorted(distribution):
            raise ValueError("setup percentile reference must be sorted and nonempty")
        # Validate all numeric leaves, including coefficients and calibration values.
        def finite(value: Any) -> bool:
            if isinstance(value, float):
                return math.isfinite(value)
            if isinstance(value, dict):
                return all(finite(v) for v in value.values())
            if isinstance(value, list):
                return all(finite(v) for v in value)
            return True
        if not finite(doc):
            raise ValueError("setup model contains nonfinite values")
        model = doc["model"]
        size = len(features)
        if doc["kind"] == "bucket":
            if len(model["edges"]) != size or any(len(e) != 2 or e != sorted(e) for e in model["edges"]):
                raise ValueError("invalid setup bucket boundaries")
            float(model["prior_mean"])
            if not isinstance(model["cells"], dict):
                raise ValueError("invalid setup bucket cells")
        elif doc["kind"] == "ridge":
            if len(model["coefficients"]) != size:
                raise ValueError("invalid setup coefficients")
            float(model["intercept"])
        elif doc["kind"] == "knn":
            if not 1 <= model["k"] <= len(model["vectors"]) or len(model["vectors"]) != len(model["outcomes"]):
                raise ValueError("invalid setup analogue table")
            if any(len(row) != size for row in model["vectors"]):
                raise ValueError("invalid setup analogue dimensions")
        else:
            float(model["baseline"])
            for tree in model["trees"]:
                if not tree:
                    raise ValueError("empty setup tree")
                for index, node in enumerate(tree):
                    if not node["leaf"] and not (0 <= node["feature"] < size and
                        index < node["left"] < len(tree) and index < node["right"] < len(tree)):
                        raise ValueError("invalid or cyclic setup tree")

    @property
    def sha256(self) -> str:
        return str(self.document["sha256"])

    def require_acceptance(self, config: AppConfig) -> None:
        card = self.document.get("scorecard", {})
        tests = card.get("tests", {})
        if set(tests) != {f"T{i}" for i in range(1, 8)} or not all(v.get("passed") is True for v in tests.values()):
            raise ValueError("setup model has not passed 7/7 acceptance tests")
        for scope in ("periods", "transfer_periods"):
            if set(card.get(scope, {})) != set(PERIODS) or not all(
                all(card[scope][p].get(f"T{i}", {}).get("passed") is True for i in range(1, 8))
                for p in PERIODS
            ):
                raise ValueError("setup model requires passing evidence in both periods and unseen pairs")
        if set(card.get("transfer_pairs", [])) != set(TRANSFER_PAIRS):
            raise ValueError("setup model requires all six unseen confirmation pairs")
        if self.document.get("strategy_signature") != strategy_signature(config):
            raise ValueError("setup model analysis or exit rules differ from runtime")
        if self.document.get("sizing_config") != config.scoring.model_dump(mode="json", exclude={"enabled", "shadow", "model_path"}):
            raise ValueError("setup model was validated with different sizing settings")

    def score(self, features: SetupFeatures | Mapping[str, float]) -> ScoreResult:
        values = features.values if isinstance(features, SetupFeatures) else features
        doc = self.document
        vector = [float(values[key]) for key in doc["features"]]
        if not all(math.isfinite(v) for v in vector):
            raise ValueError("setup scoring requires finite features")
        # Canonical precision keeps percentile ties identical in scalar and vectorized inference.
        mu = round(self.calibrate(self.predict(vector)), 12)
        reference = doc["training_distribution"]
        # Midrank prevents a constant model from assigning every trade score 100.
        percentile = 50 * (bisect_left(reference, mu) + bisect_right(reference, mu)) / len(reference)
        band = "Q" + str(min(5, int(percentile / 20) + 1))
        return ScoreResult(percentile, mu, band, self.sha256)

    def predict(self, vector: list[float]) -> float:
        doc = self.document
        model = doc["model"]
        if doc["kind"] == "bucket":
            cell = ",".join(str(bisect_left(edges, value)) for edges, value in zip(model["edges"], vector))
            return float(model["cells"].get(cell, model["prior_mean"]))
        scaled = [(value - mean) / scale for value, mean, scale in
                  zip(vector, doc["scaler"]["mean"], doc["scaler"]["scale"])]
        if doc["kind"] == "ridge":
            return float(model["intercept"] + sum(a * b for a, b in zip(scaled, model["coefficients"])))
        if doc["kind"] == "knn":
            nearest = sorted((sum((a - b) ** 2 for a, b in zip(scaled, row)), index)
                             for index, row in enumerate(model["vectors"]))[:model["k"]]
            return float(sum(model["outcomes"][i] for _, i in nearest) / len(nearest))
        prediction = float(model["baseline"])
        for tree in model["trees"]:
            index = 0
            while not tree[index]["leaf"]:
                node = tree[index]
                index = node["left"] if scaled[node["feature"]] <= node["threshold"] else node["right"]
            prediction += tree[index]["value"]
        return float(prediction)

    def calibrate(self, prediction: float) -> float:
        x, y = self.document["calibration"]["x"], self.document["calibration"]["y"]
        index = bisect_right(x, prediction)
        if index == 0:
            return float(y[0])
        if index == len(x):
            return float(y[-1])
        fraction = (prediction - x[index - 1]) / (x[index] - x[index - 1])
        return float(y[index - 1] + fraction * (y[index] - y[index - 1]))
