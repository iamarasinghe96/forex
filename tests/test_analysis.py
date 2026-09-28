from __future__ import annotations

import inspect
import math
from datetime import UTC, datetime, timedelta

import pytest

from forex.analysis import (
    Availability,
    InsufficientDataError,
    RegimeLabel,
    RelativeMacroContext,
    SetupType,
    Side,
    TradeStyle,
    analyse_market,
    atr,
    closed_candles,
    ema,
    feature_state,
    macd,
    realised_volatility,
    rsi,
    session_context,
)
from forex.config import AnalysisConfig
from forex.domain import Candle, Timeframe

START = datetime(2025, 1, 1, tzinfo=UTC)


def candles(timeframe: Timeframe, closes: list[float], *, start: datetime = START) -> list[Candle]:
    result = []
    previous = closes[0]
    for index, close in enumerate(closes):
        high, low = max(previous, close) + 0.0005, min(previous, close) - 0.0005
        result.append(Candle.from_values(
            "EURUSD", timeframe, start + timeframe.duration * index, previous, high, low,
            close, 100 + index, 12, 0,
        ))
        previous = close
    return result


def compact_config(**changes: object) -> AnalysisConfig:
    values: dict[str, object] = {
        "ema_fast": 3, "ema_slow": 5, "ema_context": 10, "rsi_period": 3,
        "macd_fast": 3, "macd_slow": 5, "macd_signal": 3, "atr_period": 3,
        "structure_window": 5, "volatility_window": 10, "slope_lookback": 2,
        "return_horizons": [1, 3, 5], "trend_threshold": 0.35,
        "setup_score_threshold": 0.2, "swing_trend_threshold": 0.45,
    }
    values.update(changes)
    return AnalysisConfig(**values)


def test_closed_candles_excludes_forming_and_uses_actual_nonstandard_h4_alignment() -> None:
    series = candles(Timeframe.H4, [1.0, 1.1, 1.2], start=datetime(2025, 7, 1, 21, tzinfo=UTC))
    evaluation = datetime(2025, 7, 2, 5, 30, tzinfo=UTC)
    assert [c.timestamp_utc.hour for c in closed_candles(series, evaluation)] == [21, 1]


def test_closed_candles_validates_series_and_utc() -> None:
    series = candles(Timeframe.H1, [1.0])
    assert closed_candles(series, START + timedelta(minutes=59)) == []
    with pytest.raises(ValueError, match="UTC"):
        closed_candles(series, datetime(2025, 1, 1, tzinfo=UTC).replace(tzinfo=None))


def test_indicator_formulas() -> None:
    assert ema([1, 2, 3], 3) == pytest.approx([1, 1.5, 2.25])
    assert rsi([1, 2, 3, 4], 3) == 100
    assert rsi([4, 3, 2, 1], 3) == 0
    line, signal, histogram = macd(list(range(1, 15)), 3, 5, 3)
    assert line > 0 and signal > 0
    assert histogram == pytest.approx(line - signal)
    sample = candles(Timeframe.H1, [1, 1.001, 1.002, 1.003])
    assert atr(sample, 3) == pytest.approx(0.002)
    assert realised_volatility([1, 1.01, 1.0, 1.02], 3) > 0


def test_features_cover_trend_momentum_volatility_structure_and_micro_context() -> None:
    config = compact_config()
    series = candles(Timeframe.H1, [1 + index * 0.001 for index in range(30)])
    values = feature_state(series, config).values
    required = {
        "ema_fast", "ema_slow", "ema_context", "ema_slope_atr", "directional_efficiency",
        "rsi", "macd", "macd_signal", "macd_histogram", "atr", "atr_normalized",
        "realised_volatility", "volatility_rank", "rolling_high", "rolling_low",
        "breakout_high_atr", "breakout_low_atr", "range_position", "mean_zscore",
        "body_ratio", "upper_wick_ratio", "lower_wick_ratio", "range_expansion",
        "directional_follow_through", "tick_volume", "broker_spread_points",
        "return_1", "return_3", "return_5",
    }
    assert required <= values.keys()
    assert values["ema_fast"] > values["ema_slow"] > values["ema_context"]
    assert values["directional_efficiency"] == pytest.approx(1)
    assert values["rolling_high"] > values["rolling_low"]


def test_insufficient_data_is_explicit() -> None:
    with pytest.raises(InsufficientDataError, match="need at least"):
        feature_state(candles(Timeframe.H1, [1, 1.1]), compact_config())


def test_trend_analysis_is_deterministic_symmetric_and_preserves_opposition() -> None:
    config = compact_config()
    h4_up = candles(Timeframe.H4, [1 + i * 0.002 for i in range(40)])
    # Last few H1 bars pull back, creating opposition without a hard veto.
    h1_up_values = [1 + i * 0.001 for i in range(37)] + [1.035, 1.034, 1.033]
    h1_up = candles(Timeframe.H1, h1_up_values)
    evaluation = max(h1_up[-1].timestamp_utc + timedelta(hours=1),
                     h4_up[-1].timestamp_utc + timedelta(hours=4))
    first = analyse_market("EURUSD", h1_up, h4_up, evaluation, config)
    second = analyse_market("EURUSD", h1_up, h4_up, evaluation, config)
    assert first == second
    assert first.snapshot.regime.label is RegimeLabel.TREND_UP
    assert first.candidate is not None
    assert first.candidate.side is Side.LONG
    assert first.candidate.setup_type is SetupType.TREND_CONTINUATION
    assert first.candidate.trade_style is TradeStyle.SWING
    assert first.candidate.opposing_evidence
    assert first.snapshot.evaluation_id == first.candidate.candidate_id
    assert first.snapshot.strategy_version and first.snapshot.parameter_version

    h4_down = candles(Timeframe.H4, [1.2 - i * 0.002 for i in range(40)])
    h1_down = candles(Timeframe.H1, [1.2 - i * 0.001 for i in range(40)])
    evaluation = max(h1_down[-1].timestamp_utc + timedelta(hours=1),
                     h4_down[-1].timestamp_utc + timedelta(hours=4))
    down = analyse_market("EURUSD", h1_down, h4_down, evaluation, config)
    assert down.candidate is not None and down.candidate.side is Side.SHORT


def test_range_candidate_and_unavailable_macro_does_not_veto() -> None:
    config = compact_config(trend_threshold=0.9, range_threshold=0.4, extreme_zscore=0.7)
    h4_values = [1 + math.sin(i) * 0.002 for i in range(40)]
    h1_values = [1 + math.sin(i) * 0.001 for i in range(39)] + [0.995]
    h4, h1 = candles(Timeframe.H4, h4_values), candles(Timeframe.H1, h1_values)
    evaluation = max(h1[-1].timestamp_utc + timedelta(hours=1),
                     h4[-1].timestamp_utc + timedelta(hours=4))
    result = analyse_market("EURUSD", h1, h4, evaluation, config)
    assert result.snapshot.regime.label is RegimeLabel.RANGE
    assert result.candidate is not None
    assert result.candidate.setup_type is SetupType.RANGE_REVERSION
    assert result.candidate.trade_style is TradeStyle.DAY
    assert result.candidate.macro_context.availability is Availability.UNAVAILABLE


def test_no_trade_snapshot_survives_for_counterfactual_learning() -> None:
    config = compact_config(trend_threshold=0.99, range_threshold=0.99)
    values = [1 + math.sin(i) * 0.001 for i in range(40)]
    h1, h4 = candles(Timeframe.H1, values), candles(Timeframe.H4, values)
    evaluation = h4[-1].timestamp_utc + timedelta(hours=4)
    result = analyse_market("EURUSD", h1, h4, evaluation, config)
    assert result.candidate is None
    assert not result.snapshot.candidate_generated
    assert result.snapshot.no_candidate_reason
    assert result.snapshot.feature_snapshot


def test_no_lookahead_and_h1_h4_synchronization() -> None:
    config = compact_config()
    h1 = candles(Timeframe.H1, [1 + i * 0.001 for i in range(41)])
    h4 = candles(Timeframe.H4, [1 + i * 0.002 for i in range(41)],
                 start=datetime(2025, 1, 1, 1, tzinfo=UTC))
    evaluation = h4[-1].timestamp_utc + timedelta(hours=3, minutes=59)
    result = analyse_market("EURUSD", h1, h4, evaluation, config)
    assert result.snapshot.last_closed_h4_utc == h4[-2].timestamp_utc
    forming_changed = list(h4)
    forming_changed[-1] = candles(Timeframe.H4, [9], start=h4[-1].timestamp_utc)[0]
    assert analyse_market("EURUSD", h1, forming_changed, evaluation, config) == result


def test_session_dst_and_overlap() -> None:
    winter = session_context(datetime(2025, 1, 15, 14, tzinfo=UTC))
    summer = session_context(datetime(2025, 7, 15, 13, tzinfo=UTC))
    assert "LONDON" in winter and "NEW_YORK" in winter
    assert "LONDON" in summer and "NEW_YORK" in summer
    assert "LONDON" not in session_context(datetime(2025, 1, 15, 7, 30, tzinfo=UTC))
    assert "LONDON" in session_context(datetime(2025, 7, 15, 7, 30, tzinfo=UTC))


def test_macro_contract_and_pure_analysis_has_no_broker_or_clock_calls() -> None:
    macro = RelativeMacroContext.unavailable("EURUSD")
    assert macro.availability is Availability.UNAVAILABLE
    assert macro.values is None and macro.source is None
    source = inspect.getsource(inspect.getmodule(analyse_market))
    assert "MetaTrader5" not in source
    assert "datetime.now" not in source
    assert "place_order" not in source
