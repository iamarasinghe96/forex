"""Broker-neutral, deterministic Layer 4 historical research.

This module deliberately imports the Layer 3 ``analyse_market`` entry point instead of
duplicating strategy rules.  It has no broker, account, order, or wall-clock dependency.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from bisect import bisect_left
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from statistics import fmean, median
from typing import Any

from forex.analysis import (
    AnalysisSnapshot,
    InsufficientDataError,
    Side,
    TradeCandidate,
    analyse_market,
    prepare_candles,
)
from forex.config import AnalysisConfig, BacktestConfig
from forex.domain import Candle, Timeframe, _require_utc
from forex.risk import ConvictionBand, RiskPolicy, derive_conviction


class ComponentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNVALIDATED = "UNVALIDATED"


class AmbiguityPolicy(str, Enum):
    ADVERSE = "adverse"
    AMBIGUOUS = "ambiguous"


class SimulationStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NO_NEXT_BAR = "NO_NEXT_BAR"
    NON_POSITIVE_INITIAL_RISK = "NON_POSITIVE_INITIAL_RISK"
    WINDOW_BOUNDARY_CENSORED = "WINDOW_BOUNDARY_CENSORED"


@dataclass(frozen=True)
class ResearchInstrumentMetadata:
    """Captured metadata; callers must obtain it from a verified broker specification."""

    symbol: str
    point: Decimal
    digits: int
    tick_size: Decimal | None = None
    pip_size: Decimal | None = None
    contract_size: Decimal | None = None

    def __post_init__(self) -> None:
        if self.point <= 0 or self.digits < 0:
            raise ValueError("captured instrument point/digits are invalid")


@dataclass(frozen=True)
class CostModel:
    """Known price costs only; missing components stay explicit rather than estimated."""

    metadata: Mapping[str, ResearchInstrumentMetadata]
    use_candle_spread: bool = True
    commission_price: Decimal | None = None
    slippage_price: Decimal | None = None
    other_price: Decimal | None = None

    @property
    def complete(self) -> bool:
        return all(value is not None for value in (
            self.commission_price, self.slippage_price, self.other_price
        ))

    def round_trip_price_cost(self, candle: Candle) -> tuple[float, Mapping[str, ComponentStatus]]:
        spec = self.metadata.get(candle.symbol)
        spread = Decimal(candle.spread) * spec.point if self.use_candle_spread and spec else None
        values = (spread, self.commission_price, self.slippage_price, self.other_price)
        names = ("spread", "commission", "slippage", "other")
        status = {
            name: ComponentStatus.AVAILABLE if value is not None else ComponentStatus.UNAVAILABLE
            for name, value in zip(names, values, strict=True)
        }
        # A candle's quoted spread is only an observed bar field, not an execution-tick spread.
        if spread is not None:
            status["spread"] = ComponentStatus.UNVALIDATED
        return float(sum((value for value in values if value is not None), Decimal(0))), status


@dataclass(frozen=True)
class ForwardPath:
    horizon_bars: int
    bars_observed: int
    reference_price: float
    forward_return: float | None
    mfe: float | None
    mae: float | None
    time_to_mfe_bars: int | None
    time_to_mae_bars: int | None


@dataclass(frozen=True)
class BacktestEvaluation:
    snapshot: AnalysisSnapshot
    candidate: TradeCandidate | None
    forward_paths: tuple[ForwardPath, ...]


@dataclass(frozen=True)
class SimulationAttempt:
    candidate_id: str
    evaluation_id: str
    status: SimulationStatus
    trade: SimulatedTrade | None


@dataclass(frozen=True)
class SimulatedTrade:
    candidate_id: str
    evaluation_id: str
    symbol: str
    side: Side
    setup_family: str
    trade_style: str
    regime: str
    volatility_bucket: str
    sessions: tuple[str, ...]
    strategy_version: str
    parameter_version: str
    signal_time_utc: datetime
    entry_time_utc: datetime
    exit_time_utc: datetime
    entry_price: float
    stop_price: float
    initial_risk: float
    exit_price: float
    exit_reason: str
    ambiguous: bool
    gross_r: float
    known_cost_r: float
    net_known_cost_r: float
    cost_status: Mapping[str, ComponentStatus]
    mfe_r: float
    mae_r: float
    time_to_mfe_bars: int
    time_to_mae_bars: int
    holding_bars: int


@dataclass(frozen=True)
class MetricSlice:
    count: int
    wins: int
    losses: int
    win_rate: float
    loss_rate: float
    average_win_r: float | None
    average_loss_r: float | None
    expectancy_r: float | None
    profit_factor: float | None
    payoff_ratio: float | None
    cumulative_r: float
    maximum_drawdown_r: float
    maximum_consecutive_losses: int
    maximum_consecutive_wins: int
    average_mae_r: float | None
    average_mfe_r: float | None
    average_holding_hours: float | None
    median_holding_hours: float | None


@dataclass(frozen=True)
class BacktestMetrics:
    evaluation_count: int
    raw_candidate_evaluation_count: int
    completed_independent_simulation_count: int
    weeks: float
    candidate_frequency_per_week: float
    setup_episode_count: int
    setup_episodes_per_week: float
    average_candidate_evaluations_per_episode: float | None
    median_candidate_evaluations_per_episode: float | None
    trades_per_week: float
    gross: MetricSlice
    net_known_cost: MetricSlice
    by_direction: Mapping[str, MetricSlice]
    by_pair: Mapping[str, MetricSlice]
    by_setup: Mapping[str, MetricSlice]
    by_regime: Mapping[str, MetricSlice]
    by_session: Mapping[str, MetricSlice]
    by_trade_style: Mapping[str, MetricSlice]
    by_volatility_bucket: Mapping[str, MetricSlice]
    by_conviction_band: Mapping[str, MetricSlice]
    conviction_distribution: tuple[float, ...]
    raw_candidates_by_conviction_band: Mapping[str, int]
    setup_episode_starts_by_conviction_band: Mapping[str, int]
    rejection_reasons: Mapping[str, int]
    simulation_status_counts: Mapping[str, int]
    strategy_version: str
    parameter_version: str

    @property
    def candidate_count(self) -> int:
        """Compatibility alias; this is a raw candidate-evaluation count."""
        return self.raw_candidate_evaluation_count

    @property
    def trade_count(self) -> int:
        """Compatibility alias; this is not a future live-order count."""
        return self.completed_independent_simulation_count


@dataclass(frozen=True)
class ReplayResult:
    evaluations: tuple[BacktestEvaluation, ...]
    simulation_attempts: tuple[SimulationAttempt, ...]
    trades: tuple[SimulatedTrade, ...]
    metrics: BacktestMetrics


def _forward_path(candles: Sequence[Candle], index: int, horizon: int,
                  outcome_end_utc: datetime | None = None) -> ForwardPath:
    future = [candle for candle in candles[index + 1:index + 1 + horizon]
              if outcome_end_utc is None
              or candle.timestamp_utc + candle.timeframe.duration <= outcome_end_utc]
    reference = float(candles[index].close)
    if not future:
        return ForwardPath(horizon, 0, reference, None, None, None, None, None)
    highs = [float(c.high) for c in future]
    lows = [float(c.low) for c in future]
    mfe_value = max(highs) - reference
    mae_value = reference - min(lows)
    return ForwardPath(horizon, len(future), reference,
                       float(future[-1].close) / reference - 1,
                       mfe_value, mae_value, highs.index(max(highs)) + 1,
                       lows.index(min(lows)) + 1)


def replay_evaluations(symbol: str, h1: Sequence[Candle], h4: Sequence[Candle],
                       analysis: AnalysisConfig, research: BacktestConfig,
                       evaluation_start_utc: datetime | None = None,
                       evaluation_end_utc: datetime | None = None,
                       outcome_end_utc: datetime | None = None) -> tuple[BacktestEvaluation, ...]:
    """Evaluate after each actual H1 close; future bars are used only for labelled outcomes."""
    ordered_h1 = sorted(h1, key=lambda c: c.timestamp_utc)
    ordered_h4 = sorted(h4, key=lambda c: c.timestamp_utc)
    prepared_h1 = prepare_candles(ordered_h1, analysis)
    prepared_h4 = prepare_candles(ordered_h4, analysis)
    results: list[BacktestEvaluation] = []
    for index, candle in enumerate(ordered_h1):
        evaluation_time = candle.timestamp_utc + Timeframe.H1.duration
        if evaluation_start_utc is not None and evaluation_time < evaluation_start_utc:
            continue
        if evaluation_end_utc is not None and evaluation_time >= evaluation_end_utc:
            continue
        try:
            # analyse_market performs its own close-time filtering. Passing immutable history makes
            # this the exact same strategy entry point used by non-research callers.
            analysed = analyse_market(symbol, prepared_h1, prepared_h4, evaluation_time, analysis)
        except InsufficientDataError:
            continue
        paths = tuple(_forward_path(ordered_h1, index, horizon, outcome_end_utc)
                      for horizon in research.forward_horizons_bars)
        results.append(BacktestEvaluation(analysed.snapshot, analysed.candidate, paths))
    return tuple(results)


def _hit_values(side: Side, candle: Candle, stop: float, target: float) -> tuple[bool, bool]:
    if side is Side.LONG:
        return float(candle.low) <= stop, float(candle.high) >= target
    return float(candle.high) >= stop, float(candle.low) <= target


def simulate_trade_attempt(candidate: TradeCandidate, future_h1: Sequence[Candle],
                           config: BacktestConfig, cost_model: CostModel | None = None,
                           outcome_end_utc: datetime | None = None) -> SimulationAttempt:
    """Simulate within an explicit outcome boundary; unresolved outcomes are censored."""
    all_future = [c for c in sorted(future_h1, key=lambda c: c.timestamp_utc)
                  if c.timestamp_utc >= candidate.evaluation_time_utc]
    bars = [c for c in all_future if outcome_end_utc is None
            or c.timestamp_utc + c.timeframe.duration <= outcome_end_utc]
    if not bars:
        status = (SimulationStatus.WINDOW_BOUNDARY_CENSORED if all_future
                  else SimulationStatus.NO_NEXT_BAR)
        return SimulationAttempt(candidate.candidate_id, candidate.evaluation_id, status, None)
    entry_bar = bars[0]
    entry = float(entry_bar.open)
    reference = candidate.structural_reference_levels
    stop = float(reference["rolling_low"] if candidate.side is Side.LONG
                 else reference["rolling_high"])
    risk = entry - stop if candidate.side is Side.LONG else stop - entry
    if risk <= 0:
        return SimulationAttempt(candidate.candidate_id, candidate.evaluation_id,
                                 SimulationStatus.NON_POSITIVE_INITIAL_RISK, None)
    target = entry + risk * config.reward_risk * (1 if candidate.side is Side.LONG else -1)
    active_stop = stop
    breakeven_reached = False
    exit_price: float | None = None
    exit_reason: str | None = None
    ambiguous = False
    exit_index = 0
    mfe = mae = 0.0
    mfe_index = mae_index = 0
    policy = AmbiguityPolicy(config.ambiguity_policy)
    for index, bar in enumerate(bars[:config.simulation_horizon_bars]):
        favorable = ((float(bar.high) - entry) if candidate.side is Side.LONG
                     else (entry - float(bar.low))) / risk
        adverse = ((entry - float(bar.low)) if candidate.side is Side.LONG
                   else (float(bar.high) - entry)) / risk
        if favorable > mfe:
            mfe, mfe_index = favorable, index
        if adverse > mae:
            mae, mae_index = adverse, index
        stop_hit, target_hit = _hit_values(candidate.side, bar, active_stop, target)
        if stop_hit and target_hit:
            ambiguous = True
            exit_index = index
            if policy is AmbiguityPolicy.ADVERSE:
                exit_price, exit_reason = active_stop, "AMBIGUOUS_STOP_FIRST"
            else:
                exit_price, exit_reason = active_stop, "AMBIGUOUS_UNRESOLVED"
            break
        if stop_hit:
            exit_price, exit_reason, exit_index = active_stop, "STOP", index
            break
        if target_hit:
            exit_price, exit_reason, exit_index = target, "TARGET", index
            break
        # Stop changes take effect only after this entire OHLC bar, avoiding favourable ordering.
        if config.breakeven_at_r is not None and favorable >= config.breakeven_at_r:
            breakeven_reached = True
            active_stop = max(active_stop, entry) if candidate.side is Side.LONG else min(active_stop, entry)
        if config.atr_trailing_multiple is not None and breakeven_reached:
            atr_value = float(candidate.feature_snapshot["h1_atr"])
            proposed = (float(bar.close) - config.atr_trailing_multiple * atr_value
                        if candidate.side is Side.LONG
                        else float(bar.close) + config.atr_trailing_multiple * atr_value)
            active_stop = max(active_stop, proposed) if candidate.side is Side.LONG else min(active_stop, proposed)
    if exit_price is None:
        if len(bars) < config.simulation_horizon_bars:
            return SimulationAttempt(candidate.candidate_id, candidate.evaluation_id,
                                     SimulationStatus.WINDOW_BOUNDARY_CENSORED, None)
        exit_index = config.simulation_horizon_bars - 1
        exit_price = float(bars[exit_index].close)
        exit_reason = "TIME"
    assert exit_reason is not None
    signed = (exit_price - entry) * (1 if candidate.side is Side.LONG else -1)
    gross_r = signed / risk
    price_cost = 0.0
    statuses: Mapping[str, ComponentStatus] = {
        name: ComponentStatus.UNAVAILABLE for name in ("spread", "commission", "slippage", "other")
    }
    if cost_model is not None:
        price_cost, statuses = cost_model.round_trip_price_cost(entry_bar)
    known_cost_r = price_cost / risk
    trade = SimulatedTrade(
        candidate.candidate_id, candidate.evaluation_id, candidate.symbol, candidate.side,
        candidate.setup_type.value, candidate.trade_style.value, candidate.h4_regime.label.value,
        ("LOW" if candidate.volatility_context < 1 / 3 else
         "MEDIUM" if candidate.volatility_context < 2 / 3 else "HIGH"),
        candidate.session_context, candidate.strategy_version, candidate.parameter_version,
        candidate.evaluation_time_utc, entry_bar.timestamp_utc,
        bars[exit_index].timestamp_utc + Timeframe.H1.duration, entry, stop, risk, exit_price,
        exit_reason, ambiguous, gross_r, known_cost_r, gross_r - known_cost_r, statuses,
        mfe, mae, mfe_index + 1, mae_index + 1, exit_index + 1,
    )
    return SimulationAttempt(candidate.candidate_id, candidate.evaluation_id,
                             SimulationStatus.COMPLETED, trade)


def simulate_trade(candidate: TradeCandidate, future_h1: Sequence[Candle], config: BacktestConfig,
                   cost_model: CostModel | None = None,
                   outcome_end_utc: datetime | None = None) -> SimulatedTrade | None:
    """Compatibility helper returning only a completed independent candidate simulation."""
    return simulate_trade_attempt(candidate, future_h1, config, cost_model,
                                  outcome_end_utc).trade


def simulate_candidates(evaluations: Sequence[BacktestEvaluation], h1: Sequence[Candle],
                        config: BacktestConfig, cost_model: CostModel | None = None,
                        outcome_end_utc: datetime | None = None) -> tuple[SimulationAttempt, ...]:
    ordered = sorted(h1, key=lambda candle: candle.timestamp_utc)
    timestamps = [candle.timestamp_utc for candle in ordered]
    attempts = []
    for item in evaluations:
        if item.candidate is None:
            continue
        start = bisect_left(timestamps, item.candidate.evaluation_time_utc)
        # The simulator can consume at most the configured horizon. Keep the first
        # future bar even across the outcome boundary so censoring remains distinct
        # from NO_NEXT_BAR. No future bars or fills are invented.
        future = ordered[start:start + config.simulation_horizon_bars]
        attempts.append(simulate_trade_attempt(
            item.candidate, future, config, cost_model, outcome_end_utc,
        ))
    return tuple(attempts)


def _streak(values: Sequence[float], predicate: Callable[[float], bool]) -> int:
    longest = current = 0
    for value in values:
        current = current + 1 if predicate(value) else 0
        longest = max(longest, current)
    return longest


def _metric_slice(trades: Sequence[SimulatedTrade], *, net: bool) -> MetricSlice:
    values = [t.net_known_cost_r if net else t.gross_r for t in trades]
    wins, losses = [v for v in values if v > 0], [v for v in values if v < 0]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    positive, negative = sum(wins), abs(sum(losses))
    return MetricSlice(
        len(values), len(wins), len(losses), len(wins) / len(values) if values else 0.0,
        len(losses) / len(values) if values else 0.0, fmean(wins) if wins else None,
        fmean(losses) if losses else None, fmean(values) if values else None,
        positive / negative if negative else (math.inf if positive else None),
        fmean(wins) / abs(fmean(losses)) if wins and losses else None, sum(values), drawdown,
        _streak(values, lambda value: value < 0), _streak(values, lambda value: value > 0),
        fmean(t.mae_r for t in trades) if trades else None,
        fmean(t.mfe_r for t in trades) if trades else None,
        fmean(t.holding_bars for t in trades) if trades else None,
        median(t.holding_bars for t in trades) if trades else None,
    )


def _breakdown(trades: Sequence[SimulatedTrade], key: Callable[[SimulatedTrade], Sequence[str] | str]) -> Mapping[str, MetricSlice]:
    groups: dict[str, list[SimulatedTrade]] = defaultdict(list)
    for trade in trades:
        value = key(trade)
        for name in value if not isinstance(value, str) else (value,):
            groups[name].append(trade)
    return {name: _metric_slice(group, net=True) for name, group in sorted(groups.items())}


def _episode_lengths(evaluations: Sequence[BacktestEvaluation]) -> list[int]:
    """Lengths of contiguous symbol/side/setup candidate runs; analytical metadata only."""
    lengths: list[int] = []
    active_key: tuple[str, Side, object] | None = None
    active_length = 0
    for evaluation in evaluations:
        candidate = evaluation.candidate
        key = ((candidate.symbol, candidate.side, candidate.setup_type)
               if candidate is not None else None)
        if key is not None and key == active_key:
            active_length += 1
            continue
        if active_length:
            lengths.append(active_length)
        active_key = key
        active_length = 1 if key is not None else 0
    if active_length:
        lengths.append(active_length)
    return lengths


def _episode_start_candidates(evaluations: Sequence[BacktestEvaluation]) -> list[TradeCandidate]:
    starts: list[TradeCandidate] = []
    active_key: tuple[str, Side, object] | None = None
    for evaluation in evaluations:
        candidate = evaluation.candidate
        key = ((candidate.symbol, candidate.side, candidate.setup_type)
               if candidate is not None else None)
        if candidate is not None and key != active_key:
            starts.append(candidate)
        active_key = key
    return starts


def calculate_metrics(evaluations: Sequence[BacktestEvaluation], trades: Sequence[SimulatedTrade],
                      policy: RiskPolicy,
                      simulation_attempts: Sequence[SimulationAttempt] = ()) -> BacktestMetrics:
    snapshots = [item.snapshot for item in evaluations]
    if snapshots:
        elapsed = max((snapshots[-1].evaluation_time_utc - snapshots[0].evaluation_time_utc).total_seconds(), 0)
        weeks = max(elapsed / (7 * 86400), 1 / 7)
        strategy, parameter = snapshots[0].strategy_version, snapshots[0].parameter_version
    else:
        weeks, strategy, parameter = 0.0, "UNKNOWN", "UNKNOWN"
    candidates = sum(item.candidate is not None for item in evaluations)
    episode_lengths = _episode_lengths(evaluations)
    rejections = Counter(item.snapshot.no_candidate_reason or "UNSPECIFIED"
                         for item in evaluations if item.candidate is None)
    candidate_items = [item.candidate for item in evaluations if item.candidate is not None]
    conviction_by_id = {candidate.candidate_id: derive_conviction(candidate, policy)
                        for candidate in candidate_items}
    conviction_counts = Counter(result.band.value for result in conviction_by_id.values())
    episode_counts = Counter(derive_conviction(candidate, policy).band.value
                             for candidate in _episode_start_candidates(evaluations))
    trades_by_band: dict[str, list[SimulatedTrade]] = defaultdict(list)
    for trade in trades:
        result = conviction_by_id.get(trade.candidate_id)
        if result is not None:
            trades_by_band[result.band.value].append(trade)
    return BacktestMetrics(
        len(evaluations), candidates, len(trades), weeks, candidates / weeks if weeks else 0,
        len(episode_lengths), len(episode_lengths) / weeks if weeks else 0,
        fmean(episode_lengths) if episode_lengths else None,
        median(episode_lengths) if episode_lengths else None,
        len(trades) / weeks if weeks else 0, _metric_slice(trades, net=False),
        _metric_slice(trades, net=True), _breakdown(trades, lambda t: t.side.value),
        _breakdown(trades, lambda t: t.symbol), _breakdown(trades, lambda t: t.setup_family),
        _breakdown(trades, lambda t: t.regime), _breakdown(trades, lambda t: t.sessions),
        _breakdown(trades, lambda t: t.trade_style),
        _breakdown(trades, lambda t: t.volatility_bucket),
        {band: _metric_slice(group, net=True) for band, group in sorted(trades_by_band.items())},
        tuple(float(result.final_conviction) for result in conviction_by_id.values()),
        {band.value: conviction_counts.get(band.value, 0) for band in ConvictionBand},
        {band.value: episode_counts.get(band.value, 0) for band in ConvictionBand},
        dict(sorted(rejections.items())),
        dict(sorted(Counter(attempt.status.value for attempt in simulation_attempts).items())),
        strategy, parameter,
    )


def run_backtest(symbol: str, h1: Sequence[Candle], h4: Sequence[Candle], analysis: AnalysisConfig,
                 research: BacktestConfig, policy: RiskPolicy, cost_model: CostModel | None = None,
                 evaluation_start_utc: datetime | None = None,
                 evaluation_end_utc: datetime | None = None,
                 outcome_end_utc: datetime | None = None) -> ReplayResult:
    evaluations = replay_evaluations(symbol, h1, h4, analysis, research,
                                     evaluation_start_utc, evaluation_end_utc, outcome_end_utc)
    attempts = simulate_candidates(evaluations, h1, research, cost_model, outcome_end_utc)
    trades = tuple(attempt.trade for attempt in attempts if attempt.trade is not None)
    return ReplayResult(evaluations, attempts, trades,
                        calculate_metrics(evaluations, trades, policy, attempts))


@dataclass(frozen=True)
class ParameterExperiment:
    experiment_id: str
    parameter_version: str
    overrides: Mapping[str, Any]
    analysis: AnalysisConfig


def parameter_experiment(base: AnalysisConfig, overrides: Mapping[str, Any]) -> ParameterExperiment:
    """Create a stable bounded experiment without modifying configuration on disk."""
    allowed = {field for field in type(base).model_fields if field not in {"strategy_version", "parameter_version"}}
    unknown = set(overrides) - allowed
    if unknown:
        raise ValueError(f"unknown or immutable experiment parameters: {sorted(unknown)}")
    canonical = json.dumps(dict(sorted(overrides.items())), sort_keys=True, separators=(",", ":"))
    identifier = hashlib.sha256(f"{base.strategy_version}|{canonical}".encode()).hexdigest()[:16]
    version = f"research-{identifier}"
    analysis = base.model_copy(update={**overrides, "parameter_version": version})
    # model_copy intentionally does not validate updates in Pydantic; reconstruct to enforce bounds.
    analysis = AnalysisConfig.model_validate(analysis.model_dump())
    return ParameterExperiment(identifier, version, dict(sorted(overrides.items())), analysis)


@dataclass(frozen=True)
class WalkForwardFold:
    fold_number: int
    train_start_utc: datetime
    train_end_utc: datetime
    test_start_utc: datetime
    test_end_utc: datetime


@dataclass(frozen=True)
class WalkForwardResult:
    folds: tuple[WalkForwardFold, ...]
    final_holdout_start_utc: datetime | None


@dataclass(frozen=True)
class WalkForwardFoldResult:
    fold: WalkForwardFold
    selected_parameter_version: str
    train_metrics: BacktestMetrics
    test_metrics: BacktestMetrics


@dataclass(frozen=True)
class WalkForwardValidation:
    fold_results: tuple[WalkForwardFoldResult, ...]
    aggregate_oos: BacktestMetrics
    final_holdout_start_utc: datetime | None
    final_holdout_evaluated: bool = False


def build_walk_forward_folds(start: datetime, end: datetime, config: BacktestConfig) -> WalkForwardResult:
    """Construct chronological train -> unseen test folds, excluding a final holdout."""
    _require_utc(start, "start")
    _require_utc(end, "end")
    if end <= start:
        raise ValueError("walk-forward end must follow start")
    holdout_start = end - timedelta(days=config.final_holdout_days) if config.final_holdout_days else None
    research_end = holdout_start or end
    folds: list[WalkForwardFold] = []
    train_start = start
    number = 1
    while True:
        train_end = train_start + timedelta(days=config.train_days)
        test_end = train_end + timedelta(days=config.test_days)
        if test_end > research_end:
            break
        folds.append(WalkForwardFold(number, train_start, train_end, train_end, test_end))
        train_start += timedelta(days=config.step_days)
        number += 1
    return WalkForwardResult(tuple(folds), holdout_start)


def run_walk_forward(symbol: str, h1: Sequence[Candle], h4: Sequence[Candle],
                     experiments: Sequence[ParameterExperiment], research: BacktestConfig,
                     policy: RiskPolicy,
                     cost_model: CostModel | None = None) -> WalkForwardValidation:
    """Select on each train window and evaluate that selection on its subsequent test only.

    The reserved final holdout is deliberately returned but never evaluated by this research loop.
    Selection uses train expectancy then trade count as deterministic ties; this is machinery, not
    a recommendation or automatic parameter promotion.
    """
    if not experiments or not h1 or not h4:
        raise ValueError("walk-forward requires experiments and H1/H4 candles")
    start = max(min(c.timestamp_utc for c in h1), min(c.timestamp_utc for c in h4))
    end = min(max(c.timestamp_utc + c.timeframe.duration for c in h1),
              max(c.timestamp_utc + c.timeframe.duration for c in h4))
    protocol = build_walk_forward_folds(start, end, research)
    results: list[WalkForwardFoldResult] = []
    oos_evaluations: list[BacktestEvaluation] = []
    oos_attempts: list[SimulationAttempt] = []
    oos_trades: list[SimulatedTrade] = []
    for fold in protocol.folds:
        train_candidates: list[tuple[float, int, str, ParameterExperiment, ReplayResult]] = []
        for experiment in experiments:
            train = run_backtest(
                symbol, h1, h4, experiment.analysis, research, policy, cost_model,
                fold.train_start_utc, fold.train_end_utc, fold.train_end_utc,
            )
            expectancy = train.metrics.net_known_cost.expectancy_r
            train_candidates.append((expectancy if expectancy is not None else -math.inf,
                                     train.metrics.trade_count, experiment.parameter_version,
                                     experiment, train))
        # Version in the key makes ties stable regardless of input order.
        _, _, _, selected, train = max(train_candidates, key=lambda item: item[:3])
        test = run_backtest(
            symbol, h1, h4, selected.analysis, research, policy, cost_model,
            fold.test_start_utc, fold.test_end_utc, fold.test_end_utc,
        )
        results.append(WalkForwardFoldResult(fold, selected.parameter_version,
                                             train.metrics, test.metrics))
        oos_evaluations.extend(test.evaluations)
        oos_attempts.extend(test.simulation_attempts)
        oos_trades.extend(test.trades)
    aggregate = calculate_metrics(oos_evaluations, oos_trades, policy, oos_attempts)
    return WalkForwardValidation(tuple(results), aggregate, protocol.final_holdout_start_utc)


@dataclass(frozen=True)
class Distribution:
    minimum: float
    percentile_05: float
    median: float
    percentile_95: float
    maximum: float


@dataclass(frozen=True)
class MonteCarloSummary:
    iterations: int
    seed: int
    method: str
    expectancy_r: Distribution
    cumulative_r: Distribution
    max_drawdown_r: Distribution
    longest_loss_streak: Distribution
    longest_win_streak: Distribution
    limitation: str


def _distribution(values: Sequence[float]) -> Distribution:
    ordered = sorted(values)
    def percentile(fraction: float) -> float:
        return ordered[round((len(ordered) - 1) * fraction)]
    return Distribution(ordered[0], percentile(.05), percentile(.5), percentile(.95), ordered[-1])


def monte_carlo(trades: Sequence[SimulatedTrade], iterations: int, seed: int) -> MonteCarloSummary:
    if not trades or iterations < 1:
        raise ValueError("Monte Carlo requires completed trades and positive iterations")
    source = [trade.net_known_cost_r for trade in trades]
    rng = random.Random(seed)
    expectancy: list[float] = []
    cumulative: list[float] = []
    drawdowns: list[float] = []
    loss_streaks: list[float] = []
    win_streaks: list[float] = []
    for _ in range(iterations):
        sample = rng.choices(source, k=len(source))
        equity = peak = drawdown = 0.0
        for value in sample:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        expectancy.append(fmean(sample))
        cumulative.append(sum(sample))
        drawdowns.append(drawdown)
        loss_streaks.append(float(_streak(sample, lambda value: value < 0)))
        win_streaks.append(float(_streak(sample, lambda value: value > 0)))
    return MonteCarloSummary(iterations, seed, "IID trade-outcome bootstrap",
                             _distribution(expectancy), _distribution(cumulative),
                             _distribution(drawdowns), _distribution(loss_streaks),
                             _distribution(win_streaks),
                             "IID resampling may understate serial and regime dependence; it does not create market history.")


@dataclass(frozen=True)
class HistoryGate:
    sufficient: bool
    required_years: float
    available_years: float
    status: str
    h1_count: int
    h4_count: int
    earliest_utc: datetime | None
    latest_utc: datetime | None


def history_gate(h1: Sequence[Candle], h4: Sequence[Candle], required_years: float = 5.0) -> HistoryGate:
    if not h1 or not h4:
        return HistoryGate(False, required_years, 0.0,
                           "INSUFFICIENT HISTORY FOR FIVE-YEAR VALIDATION",
                           len(h1), len(h4), None, None)
    def span(candles: Sequence[Candle]) -> float:
        ordered = sorted(candles, key=lambda candle: candle.timestamp_utc)
        return (ordered[-1].timestamp_utc - ordered[0].timestamp_utc).total_seconds() / (365.2425 * 86400)
    years = min(span(h1), span(h4))
    sufficient = years >= required_years
    earliest = max(min(c.timestamp_utc for c in h1), min(c.timestamp_utc for c in h4))
    latest = min(max(c.timestamp_utc + c.timeframe.duration for c in h1),
                 max(c.timestamp_utc + c.timeframe.duration for c in h4))
    return HistoryGate(sufficient, required_years, years,
                       "ELIGIBLE FOR FORMAL VALIDATION" if sufficient
                       else "INSUFFICIENT HISTORY FOR FIVE-YEAR VALIDATION",
                       len(h1), len(h4), earliest, latest)


@dataclass(frozen=True)
class StrategyBaseline:
    generated_at_utc: datetime
    validation_status: str
    history: Mapping[str, HistoryGate]
    metrics_by_symbol: Mapping[str, BacktestMetrics]
    monte_carlo_by_symbol: Mapping[str, MonteCarloSummary | None]
    cost_model_complete: bool
    walk_forward_protocol: Mapping[str, WalkForwardResult]
    assumptions: Mapping[str, object]
    warnings: tuple[str, ...]
    research_dataset: Mapping[str, object] | None = None


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def write_json_report(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
