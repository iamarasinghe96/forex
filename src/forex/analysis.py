"""Pure, deterministic Layer 3 feature, regime, and candidate analysis."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from statistics import fmean, pstdev
from types import MappingProxyType
from zoneinfo import ZoneInfo

from forex.config import AnalysisConfig
from forex.domain import Candle, Timeframe, _require_utc


class InsufficientDataError(ValueError):
    """Raised when closed history cannot support configured feature windows."""


class RegimeLabel(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    UNCERTAIN = "UNCERTAIN"


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SetupType(str, Enum):
    TREND_CONTINUATION = "TREND_CONTINUATION_BREAKOUT_PULLBACK"
    RANGE_REVERSION = "RANGE_MEAN_REVERSION"


class TradeStyle(str, Enum):
    DAY = "DAY"
    SWING = "SWING"


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class Evidence:
    code: str
    strength: float
    detail: str


@dataclass(frozen=True)
class RelativeMacroContext:
    pair: str
    base_currency: str
    quote_currency: str
    availability: Availability
    source: str | None = None
    observed_at_utc: datetime | None = None
    effective_at_utc: datetime | None = None
    freshness_seconds: float | None = None
    values: Mapping[str, float] | None = None
    signals: tuple[str, ...] = ()

    @classmethod
    def unavailable(cls, pair: str) -> RelativeMacroContext:
        pair = pair.upper()
        return cls(pair, pair[:3], pair[3:6], Availability.UNAVAILABLE)


@dataclass(frozen=True)
class FeatureState:
    values: Mapping[str, float]


@dataclass(frozen=True)
class RegimeState:
    label: RegimeLabel
    directional_bias: float
    trend_strength: float
    range_strength: float
    volatility_state: float
    momentum_state: float
    structural_breakout_state: float


@dataclass(frozen=True)
class TradeCandidate:
    candidate_id: str
    evaluation_id: str
    symbol: str
    evaluation_time_utc: datetime
    data_cutoff_utc: datetime
    side: Side
    setup_type: SetupType
    trade_style: TradeStyle
    style_reason: str
    strategy_version: str
    parameter_version: str
    h4_regime: RegimeState
    directional_evidence: float
    setup_strength_components: Mapping[str, float]
    volatility_context: float
    structural_context: Mapping[str, float]
    supporting_evidence: tuple[Evidence, ...]
    opposing_evidence: tuple[Evidence, ...]
    uncertainty: float
    structural_reference_levels: Mapping[str, float]
    feature_snapshot: Mapping[str, float]
    macro_context: RelativeMacroContext
    session_context: tuple[str, ...]


@dataclass(frozen=True)
class AnalysisSnapshot:
    evaluation_id: str
    symbol: str
    evaluation_time_utc: datetime
    data_cutoff_utc: datetime
    last_closed_h1_utc: datetime
    last_closed_h4_utc: datetime
    strategy_version: str
    parameter_version: str
    feature_snapshot: Mapping[str, float]
    regime: RegimeState
    setup_measurements: Mapping[str, float]
    candidate_generated: bool
    direction: Side | None
    setup_type: SetupType | None
    trade_style: TradeStyle | None
    style_reason: str | None
    supporting_evidence: tuple[Evidence, ...]
    opposing_evidence: tuple[Evidence, ...]
    no_candidate_reason: str | None
    session_context: tuple[str, ...]
    volatility_state: float
    macro_context: RelativeMacroContext


@dataclass(frozen=True)
class AnalysisResult:
    snapshot: AnalysisSnapshot
    candidate: TradeCandidate | None


def closed_candles(candles: Sequence[Candle], evaluation_time: datetime) -> list[Candle]:
    """Return ordered, unique candles whose actual timestamp plus duration is closed."""
    _require_utc(evaluation_time, "evaluation_time")
    if not candles:
        return []
    symbol, timeframe = candles[0].symbol, candles[0].timeframe
    if any(c.symbol != symbol or c.timeframe is not timeframe for c in candles):
        raise ValueError("candle series must contain one symbol and timeframe")
    unique = {c.timestamp_utc: c for c in candles}
    return [unique[key] for key in sorted(unique) if key + timeframe.duration <= evaluation_time]


def ema(values: Sequence[float], period: int) -> list[float]:
    if period < 1 or not values:
        raise ValueError("EMA needs values and a positive period")
    alpha = 2.0 / (period + 1)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1 - alpha) * result[-1])
    return result


def rsi(values: Sequence[float], period: int) -> float:
    if len(values) < period + 1:
        raise InsufficientDataError("RSI requires period + 1 values")
    changes = [values[i] - values[i - 1] for i in range(len(values) - period, len(values))]
    gain = fmean(max(change, 0.0) for change in changes)
    loss = fmean(max(-change, 0.0) for change in changes)
    if loss == 0:
        return 100.0 if gain else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def macd(values: Sequence[float], fast: int, slow: int, signal: int) -> tuple[float, float, float]:
    if len(values) < slow + signal:
        raise InsufficientDataError("MACD requires slow + signal values")
    fast_line, slow_line = ema(values, fast), ema(values, slow)
    line = [a - b for a, b in zip(fast_line, slow_line, strict=True)]
    signal_value = ema(line, signal)[-1]
    return line[-1], signal_value, line[-1] - signal_value


def atr(candles: Sequence[Candle], period: int) -> float:
    if len(candles) < period + 1:
        raise InsufficientDataError("ATR requires period + 1 candles")
    ranges = []
    for previous, candle in zip(candles[-period - 1:-1], candles[-period:], strict=True):
        ranges.append(max(float(candle.high - candle.low),
                          abs(float(candle.high - previous.close)),
                          abs(float(candle.low - previous.close))))
    return fmean(ranges)


def realised_volatility(values: Sequence[float], period: int) -> float:
    if len(values) < period + 1:
        raise InsufficientDataError("realised volatility requires period + 1 values")
    returns = [math.log(values[i] / values[i - 1]) for i in range(len(values) - period, len(values))]
    return pstdev(returns)


def _rank(value: float, values: Sequence[float]) -> float:
    return sum(item <= value for item in values) / len(values)


def feature_state(candles: Sequence[Candle], config: AnalysisConfig) -> FeatureState:
    required = max(config.ema_context + config.slope_lookback,
                   config.volatility_window + config.atr_period + 1,
                   max(config.return_horizons) + 1, config.macd_slow + config.macd_signal)
    if len(candles) < required:
        raise InsufficientDataError(f"need at least {required} closed candles, found {len(candles)}")
    closes = [float(c.close) for c in candles]
    fast, slow, context = (ema(closes, period) for period in
                           (config.ema_fast, config.ema_slow, config.ema_context))
    price = closes[-1]
    atr_value = atr(candles, config.atr_period)
    atr_history = [atr(candles[:end], config.atr_period)
                   for end in range(len(candles) - config.volatility_window + 1, len(candles) + 1)]
    high = max(float(c.high) for c in candles[-config.structure_window - 1:-1])
    low = min(float(c.low) for c in candles[-config.structure_window - 1:-1])
    width = max(high - low, 1e-12)
    movements = sum(abs(closes[i] - closes[i - 1]) for i in range(
        len(closes) - config.structure_window + 1, len(closes)))
    efficiency = abs(closes[-1] - closes[-config.structure_window]) / max(movements, 1e-12)
    macd_line, macd_signal, macd_hist = macd(
        closes, config.macd_fast, config.macd_slow, config.macd_signal)
    recent = candles[-1]
    body = abs(float(recent.close - recent.open))
    candle_range = max(float(recent.high - recent.low), 1e-12)
    mean = fmean(closes[-config.structure_window:])
    deviation = pstdev(closes[-config.structure_window:])
    values: dict[str, float] = {
        "close": price, "ema_fast": fast[-1], "ema_slow": slow[-1],
        "ema_context": context[-1], "distance_fast_atr": (price - fast[-1]) / atr_value,
        "distance_slow_atr": (price - slow[-1]) / atr_value,
        "ema_fast_slow_atr": (fast[-1] - slow[-1]) / atr_value,
        "ema_slope_atr": (fast[-1] - fast[-1 - config.slope_lookback]) / atr_value,
        "directional_efficiency": efficiency, "rsi": rsi(closes, config.rsi_period),
        "macd": macd_line, "macd_signal": macd_signal, "macd_histogram": macd_hist,
        "atr": atr_value, "atr_normalized": atr_value / price,
        "realised_volatility": realised_volatility(closes, config.atr_period),
        "volatility_rank": _rank(atr_value, atr_history),
        "rolling_high": high, "rolling_low": low,
        "breakout_high_atr": (price - high) / atr_value,
        "breakout_low_atr": (low - price) / atr_value,
        "range_position": (price - low) / width,
        "mean_zscore": (price - mean) / deviation if deviation else 0.0,
        "body_ratio": body / candle_range,
        "upper_wick_ratio": (float(recent.high) - max(float(recent.open), price)) / candle_range,
        "lower_wick_ratio": (min(float(recent.open), price) - float(recent.low)) / candle_range,
        "range_expansion": candle_range / atr_value,
        "directional_follow_through": sum(
            1 if closes[i] > closes[i - 1] else -1 if closes[i] < closes[i - 1] else 0
            for i in range(len(closes) - 5, len(closes))) / 5,
        "tick_volume": float(recent.tick_volume), "broker_spread_points": float(recent.spread),
    }
    for horizon in config.return_horizons:
        values[f"return_{horizon}"] = price / closes[-1 - horizon] - 1
    return FeatureState(MappingProxyType(values))


def calculate_regime(features: FeatureState, config: AnalysisConfig) -> RegimeState:
    v = features.values
    direction = math.tanh((v["ema_fast_slow_atr"] + v["ema_slope_atr"] +
                           v["directional_follow_through"]) / 2)
    trend = min(1.0, 0.45 * abs(direction) + 0.55 * v["directional_efficiency"])
    range_strength = max(0.0, min(1.0, 1 - trend))
    momentum = math.tanh(v["macd_histogram"] / max(v["atr"], 1e-12) +
                         (v["rsi"] - 50) / 25)
    breakout = max(-1.0, min(1.0, v["breakout_high_atr"] - v["breakout_low_atr"]))
    vol = v["volatility_rank"]
    if vol >= 0.9:
        label = RegimeLabel.HIGH_VOLATILITY
    elif trend >= config.trend_threshold and direction > 0.15:
        label = RegimeLabel.TREND_UP
    elif trend >= config.trend_threshold and direction < -0.15:
        label = RegimeLabel.TREND_DOWN
    elif range_strength >= config.range_threshold:
        label = RegimeLabel.RANGE
    elif abs(direction) < 0.1:
        label = RegimeLabel.UNCERTAIN
    else:
        label = RegimeLabel.TRANSITION
    return RegimeState(label, direction, trend, range_strength, vol, momentum, breakout)


def session_context(value: datetime) -> tuple[str, ...]:
    _require_utc(value, "session timestamp")
    sessions: list[str] = []
    # Local wall-clock definitions are metadata and intentionally overlap.
    if 9 <= value.astimezone(ZoneInfo("Asia/Tokyo")).hour < 18:
        sessions.append("ASIA")
    if 8 <= value.astimezone(ZoneInfo("Europe/London")).hour < 17:
        sessions.append("LONDON")
    if 8 <= value.astimezone(ZoneInfo("America/New_York")).hour < 17:
        sessions.append("NEW_YORK")
    return tuple(sessions or ["OFF_SESSION"])


def _evaluation_id(version: str, symbol: str, closed_h1: datetime) -> str:
    key = f"{version}|{symbol.upper()}|{closed_h1.isoformat()}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _candidate_logic(h1: FeatureState, regime: RegimeState, config: AnalysisConfig) -> tuple[
    Side | None, SetupType | None, dict[str, float], list[Evidence], list[Evidence], str | None
]:
    v = h1.values
    support: list[Evidence] = []
    oppose: list[Evidence] = []
    components: dict[str, float] = {}
    side: Side | None = None
    setup: SetupType | None = None
    if regime.label in (RegimeLabel.TREND_UP, RegimeLabel.TREND_DOWN):
        side = Side.LONG if regime.directional_bias > 0 else Side.SHORT
        sign = 1 if side is Side.LONG else -1
        components = {"h4_trend": regime.trend_strength,
                      "h1_momentum": max(0.0, sign * math.tanh(v["macd_histogram"] /
                                                               max(v["atr"], 1e-12))),
                      "structure": max(0.0, sign * (v["range_position"] - 0.5) * 2),
                      "pullback_coherence": max(0.0, 1 - abs(v["distance_fast_atr"]) / 3)}
        score = fmean(components.values())
        support.append(Evidence("H4_DIRECTIONAL_TREND", regime.trend_strength,
                                "H4 directional persistence supports continuation"))
        if sign * v["macd_histogram"] >= 0:
            support.append(Evidence("H1_MOMENTUM_ALIGNED", components["h1_momentum"],
                                    "H1 MACD histogram aligns with direction"))
        else:
            oppose.append(Evidence("H1_MOMENTUM_OPPOSED", min(1.0, abs(v["macd_histogram"] / v["atr"])),
                                   "H1 momentum currently opposes H4 direction"))
        setup = SetupType.TREND_CONTINUATION
        if score < config.setup_score_threshold:
            return None, None, components, support, oppose, "trend setup strength below UNVALIDATED threshold"
    elif regime.label is RegimeLabel.RANGE:
        if v["mean_zscore"] <= -config.extreme_zscore:
            side = Side.LONG
        elif v["mean_zscore"] >= config.extreme_zscore:
            side = Side.SHORT
        else:
            return None, None, {"range_extreme": abs(v["mean_zscore"])}, support, oppose, \
                "price is not at a configured range extreme"
        sign = 1 if side is Side.LONG else -1
        components = {"h4_range": regime.range_strength,
                      "range_extreme": min(1.0, abs(v["mean_zscore"]) / 2),
                      "reversion_momentum": max(0.0, sign * (50 - v["rsi"]) / 50)}
        support.append(Evidence("H4_RANGE", regime.range_strength,
                                "H4 low directional persistence supports reversion"))
        support.append(Evidence("H1_RANGE_EXTREME", components["range_extreme"],
                                "H1 price is displaced from its rolling mean"))
        if sign * (50 - v["rsi"]) < 0:
            oppose.append(Evidence("MOMENTUM_NOT_EXHAUSTED", abs(50 - v["rsi"]) / 50,
                                   "momentum has not yet turned toward the mean"))
        setup = SetupType.RANGE_REVERSION
        if fmean(components.values()) < config.setup_score_threshold:
            return None, None, components, support, oppose, "range setup strength below UNVALIDATED threshold"
    else:
        return None, None, {}, support, oppose, f"H4 regime {regime.label.value} has no coherent setup family"
    return side, setup, components, support, oppose, None


def analyse_market(symbol: str, h1: Sequence[Candle], h4: Sequence[Candle],
                   evaluation_time: datetime, config: AnalysisConfig,
                   macro: RelativeMacroContext | None = None) -> AnalysisResult:
    """Evaluate one immutable market state; performs no I/O and has no clock dependency."""
    _require_utc(evaluation_time, "evaluation_time")
    closed_h1, closed_h4 = closed_candles(h1, evaluation_time), closed_candles(h4, evaluation_time)
    if not closed_h1 or not closed_h4:
        raise InsufficientDataError("both H1 and H4 require closed candles")
    if closed_h4[-1].timestamp_utc + Timeframe.H4.duration > evaluation_time:
        raise ValueError("H4 synchronization violated")
    h1_features, h4_features = feature_state(closed_h1, config), feature_state(closed_h4, config)
    regime = calculate_regime(h4_features, config)
    side, setup, components, support, oppose, no_reason = _candidate_logic(
        h1_features, regime, config)
    cutoff = max(closed_h1[-1].timestamp_utc + Timeframe.H1.duration,
                 closed_h4[-1].timestamp_utc + Timeframe.H4.duration)
    evaluation_id = _evaluation_id(config.strategy_version, symbol, closed_h1[-1].timestamp_utc)
    combined = MappingProxyType({**{f"h1_{k}": value for k, value in h1_features.values.items()},
                                 **{f"h4_{k}": value for k, value in h4_features.values.items()}})
    macro = macro or RelativeMacroContext.unavailable(symbol)
    style: TradeStyle | None = None
    style_reason: str | None = None
    if setup is SetupType.RANGE_REVERSION:
        style, style_reason = TradeStyle.DAY, "H1 range reversion is expected to resolve locally"
    elif setup is SetupType.TREND_CONTINUATION:
        if regime.trend_strength >= config.swing_trend_threshold:
            style, style_reason = TradeStyle.SWING, "persistent H4 trend dominates the H1 trigger"
        else:
            style, style_reason = TradeStyle.DAY, "H1 continuation lacks persistent H4 swing evidence"
    snapshot = AnalysisSnapshot(
        evaluation_id, symbol.upper(), evaluation_time, cutoff, closed_h1[-1].timestamp_utc,
        closed_h4[-1].timestamp_utc, config.strategy_version, config.parameter_version, combined,
        regime, MappingProxyType(components), side is not None, side, setup, style, style_reason,
        tuple(support), tuple(oppose), no_reason, session_context(evaluation_time),
        regime.volatility_state, macro)
    if side is None or setup is None or style is None or style_reason is None:
        return AnalysisResult(snapshot, None)
    score = fmean(components.values())
    candidate = TradeCandidate(
        evaluation_id, evaluation_id, symbol.upper(), evaluation_time, cutoff, side, setup, style,
        style_reason, config.strategy_version, config.parameter_version, regime,
        regime.directional_bias, MappingProxyType(components), regime.volatility_state,
        MappingProxyType({"range_position": h1_features.values["range_position"],
                          "mean_zscore": h1_features.values["mean_zscore"]}),
        tuple(support), tuple(oppose), max(0.0, 1 - score),
        MappingProxyType({"rolling_high": h1_features.values["rolling_high"],
                          "rolling_low": h1_features.values["rolling_low"]}),
        combined, macro, session_context(evaluation_time))
    return AnalysisResult(snapshot, candidate)
