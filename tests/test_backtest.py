from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from forex.analysis import (
    AnalysisResult,
    AnalysisSnapshot,
    Availability,
    RegimeLabel,
    RegimeState,
    RelativeMacroContext,
    SetupType,
    Side,
    TradeCandidate,
    TradeStyle,
)
from forex.backtest import (
    AmbiguityPolicy,
    CostModel,
    ResearchInstrumentMetadata,
    SimulationStatus,
    build_walk_forward_folds,
    calculate_metrics,
    history_gate,
    monte_carlo,
    parameter_experiment,
    replay_evaluations,
    run_backtest,
    run_walk_forward,
    simulate_trade,
    simulate_trade_attempt,
)
from forex.config import AnalysisConfig, BacktestConfig
from forex.domain import Candle, Timeframe
from forex.persistence import CandleStore
from forex.risk import RiskPolicy

START = datetime(2020, 1, 1, tzinfo=UTC)
POLICY = RiskPolicy(30, Decimal("1.5"), 4, Decimal(".20"),
                    Decimal(".12"), Decimal(55), Decimal(70), Decimal(85),
                    Decimal(".02"), Decimal(".035"), Decimal(".05"))


@pytest.mark.parametrize("formal", [False, True])
def test_cli_baseline_preserves_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, formal: bool,
) -> None:
    from forex.cli import verify_backtest
    from forex.config import load_config

    monkeypatch.setattr("forex.backtest.analyse_market", fake_analysis)
    config = load_config(Path("config.yaml"))
    config.broker.symbols = ["EURUSD"]
    config.database.path = tmp_path / "history.sqlite3"
    config.backtest.report_directory = tmp_path / "reports"
    config.backtest.final_holdout_days = 2
    config.backtest.monte_carlo_iterations = 10
    monkeypatch.setattr("forex.cli.load_config", lambda path: config)
    monkeypatch.setattr("forex.cli.configure_logging", lambda config: None)
    store = CandleStore(config.database.path)
    h1 = [candle(i) for i in range(24 * 12)]
    h4 = [candle(i, Timeframe.H4) for i in range(24 * 12 // 4)]
    store.upsert(h1 + h4)
    expected_code = 3 if formal else 0
    assert verify_backtest(Path("unused"), formal=formal) == expected_code
    report = config.backtest.report_directory / "strategy-baseline.json"
    before = json.loads(report.read_text())
    boundary = datetime.fromisoformat(
        before["walk_forward_protocol"]["EURUSD"]["final_holdout_start_utc"]
    )
    assert datetime.fromisoformat(before["generated_at_utc"]) < boundary
    assert before["assumptions"]["final_holdout_evaluated"] is False
    assert before["assumptions"]["walk_forward_executed"] is False
    store.upsert([
        replace(item, open=Decimal(2), high=Decimal(3), low=Decimal(1), close=Decimal(2))
        for item in h1 + h4 if item.timestamp_utc >= boundary
    ])
    assert verify_backtest(Path("unused"), formal=formal) == expected_code
    assert json.loads(report.read_text()) == before


def candle(index: int, timeframe: Timeframe = Timeframe.H1, *, open_: float = 1.1,
           high: float = 1.11, low: float = 1.09, close: float = 1.1,
           spread: int = 2, offset_hours: int = 0) -> Candle:
    hours = index * (1 if timeframe is Timeframe.H1 else 4) + offset_hours
    return Candle.from_values("EURUSD", timeframe, START + timedelta(hours=hours), open_, high,
                              low, close, 100, spread, 0)


def series(count: int, timeframe: Timeframe, *, offset_hours: int = 0) -> list[Candle]:
    result = []
    for index in range(count):
        price = 1.0 + index * .0001
        result.append(candle(index, timeframe, open_=price, high=price + .0008,
                             low=price - .0008, close=price + .0002,
                             offset_hours=offset_hours))
    return result


def candidate(side: Side = Side.LONG, evaluation: datetime = START) -> TradeCandidate:
    regime = RegimeState(RegimeLabel.TREND_UP, .8, .8, .2, .4, .5, .2)
    features = MappingProxyType({"h1_atr": .01})
    levels = MappingProxyType({"rolling_low": .9, "rolling_high": 1.1})
    macro = RelativeMacroContext("EURUSD", "EUR", "USD", Availability.UNAVAILABLE)
    return TradeCandidate(
        "candidate", "evaluation", "EURUSD", evaluation, evaluation, side,
        SetupType.TREND_CONTINUATION, TradeStyle.DAY, "test", "layer3-v1",
        "unvalidated-v1", regime, .8, MappingProxyType({"score": .8}), .4,
        MappingProxyType({}), (), (), .2, levels, features, macro, ("LONDON",),
    )


def test_replay_is_sequential_excludes_forming_bars_and_uses_real_h4_alignment() -> None:
    h1 = series(1000, Timeframe.H1)
    # IC Markets normalized H4 timestamps may be 21:00/22:00 based; never modulo-four UTC.
    h4 = series(260, Timeframe.H4, offset_hours=2)
    result = replay_evaluations("EURUSD", h1, h4, AnalysisConfig(), BacktestConfig())
    assert result
    assert all(item.snapshot.last_closed_h1_utc + timedelta(hours=1)
               <= item.snapshot.evaluation_time_utc for item in result)
    assert all(item.snapshot.last_closed_h4_utc + timedelta(hours=4)
               <= item.snapshot.evaluation_time_utc for item in result)
    assert all(item.snapshot.evaluation_time_utc < result[index + 1].snapshot.evaluation_time_utc
               for index, item in enumerate(result[:-1]))
    assert any(item.snapshot.last_closed_h4_utc.hour % 4 == 2 for item in result)


def test_future_mutation_does_not_change_an_earlier_evaluation() -> None:
    h1, h4 = series(1000, Timeframe.H1), series(260, Timeframe.H4, offset_hours=1)
    config = BacktestConfig(forward_horizons_bars=[1])
    before = replay_evaluations("EURUSD", h1, h4, AnalysisConfig(), config)
    changed = list(h1)
    changed[-1] = candle(999, open_=2, high=3, low=1, close=2.5)
    after = replay_evaluations("EURUSD", changed, h4, AnalysisConfig(), config)
    assert before[0].snapshot == after[0].snapshot


def test_next_bar_fill_long_stop_target_and_adverse_ambiguity() -> None:
    signal = START + timedelta(hours=1)
    bars = [candle(1, open_=1.0, high=1.16, low=.89, close=1.1)]
    trade = simulate_trade(candidate(evaluation=signal), bars,
                           BacktestConfig(simulation_horizon_bars=1, breakeven_at_r=None))
    assert trade is not None
    assert trade.entry_time_utc == signal
    assert trade.entry_price == 1.0
    assert trade.ambiguous
    assert trade.exit_reason == "AMBIGUOUS_STOP_FIRST"
    assert trade.gross_r == pytest.approx(-1)


def test_short_target_and_no_signal_bar_fill() -> None:
    signal = START + timedelta(hours=1)
    bars = [candle(0, open_=1, high=2, low=.5, close=1),
            candle(1, open_=1, high=1.05, low=.84, close=.85)]
    trade = simulate_trade(candidate(Side.SHORT, signal), bars,
                           BacktestConfig(simulation_horizon_bars=1, breakeven_at_r=None))
    assert trade is not None
    assert trade.entry_time_utc == signal
    assert trade.gross_r == pytest.approx(1.5)


def test_breakeven_and_atr_trailing_changes_apply_on_following_bar() -> None:
    bars = [candle(1, open_=1, high=1.11, low=.95, close=1.08),
            candle(2, open_=1.08, high=1.09, low=.99, close=1.0)]
    trade = simulate_trade(candidate(evaluation=START + timedelta(hours=1)), bars,
                           BacktestConfig(simulation_horizon_bars=2, reward_risk=2,
                                          breakeven_at_r=1, atr_trailing_multiple=2))
    assert trade is not None
    assert trade.exit_price == 1.06  # close 1.08 - 2 * captured ATR .01
    assert trade.exit_reason == "STOP"


def test_spread_cost_is_known_but_unvalidated_and_unknowns_remain_explicit() -> None:
    model = CostModel({"EURUSD": ResearchInstrumentMetadata("EURUSD", Decimal("0.00001"), 5)})
    trade = simulate_trade(candidate(evaluation=START + timedelta(hours=1)),
                           [candle(1, open_=1, high=1.16, low=.95, close=1.15, spread=2)],
                           BacktestConfig(simulation_horizon_bars=1, breakeven_at_r=None), model)
    assert trade is not None
    assert trade.known_cost_r == pytest.approx(.0002)
    assert trade.net_known_cost_r < trade.gross_r
    assert trade.cost_status["spread"].value == "UNVALIDATED"
    assert trade.cost_status["commission"].value == "UNAVAILABLE"
    assert not model.complete


def test_metrics_breakdowns_expectancy_drawdown_streaks_and_frequency() -> None:
    bars = [candle(1, open_=1, high=1.16, low=.95, close=1.15),
            candle(2, open_=1, high=1.05, low=.89, close=.9)]
    win = simulate_trade(candidate(evaluation=START + timedelta(hours=1)), bars[:1],
                         BacktestConfig(simulation_horizon_bars=1, breakeven_at_r=None))
    loss = simulate_trade(candidate(evaluation=START + timedelta(hours=2)), bars[1:],
                          BacktestConfig(simulation_horizon_bars=1, breakeven_at_r=None))
    assert win and loss
    metrics = calculate_metrics([], [win, loss], POLICY)
    assert metrics.gross.expectancy_r == pytest.approx(.25)
    assert metrics.gross.maximum_drawdown_r == pytest.approx(1)
    assert metrics.gross.maximum_consecutive_losses == 1
    assert set(metrics.by_pair) == {"EURUSD"}
    assert set(metrics.by_setup) == {SetupType.TREND_CONTINUATION.value}
    assert set(metrics.by_regime) == {RegimeLabel.TREND_UP.value}
    assert set(metrics.by_session) == {"LONDON"}
    assert set(metrics.by_trade_style) == {"DAY"}


def test_parameter_ids_are_deterministic_bounded_and_do_not_promote_base() -> None:
    base = AnalysisConfig()
    first = parameter_experiment(base, {"rsi_period": 10, "trend_threshold": .6})
    second = parameter_experiment(base, {"trend_threshold": .6, "rsi_period": 10})
    assert first.experiment_id == second.experiment_id
    assert first.parameter_version.startswith("research-")
    assert base.parameter_version == "unvalidated-v1"
    with pytest.raises(ValueError):
        parameter_experiment(base, {"strategy_version": "changed"})


def test_walk_forward_and_final_holdout_are_chronologically_isolated() -> None:
    config = BacktestConfig(train_days=10, test_days=3, step_days=3, final_holdout_days=5)
    result = build_walk_forward_folds(START, START + timedelta(days=30), config)
    assert result.folds
    assert result.final_holdout_start_utc == START + timedelta(days=25)
    assert all(fold.train_end_utc == fold.test_start_utc for fold in result.folds)
    assert all(fold.test_end_utc <= result.final_holdout_start_utc for fold in result.folds)


def test_monte_carlo_seed_is_reproducible_and_not_account_probability() -> None:
    trade = simulate_trade(candidate(evaluation=START + timedelta(hours=1)),
                           [candle(1, open_=1, high=1.16, low=.95, close=1.15)],
                           BacktestConfig(simulation_horizon_bars=1, breakeven_at_r=None))
    assert trade
    first = monte_carlo([trade], 10, 42)
    assert first == monte_carlo([trade], 10, 42)
    assert "IID" in first.method


def test_five_year_gate_refuses_short_engine_verification_data() -> None:
    short_h1, short_h4 = series(100, Timeframe.H1), series(100, Timeframe.H4)
    gate = history_gate(short_h1, short_h4)
    assert not gate.sufficient
    assert gate.status == "INSUFFICIENT HISTORY FOR FIVE-YEAR VALIDATION"
    long_h1 = [candle(0), candle(24 * 366 * 5)]
    long_h4 = [candle(0, Timeframe.H4), candle(24 * 366 * 5 // 4, Timeframe.H4)]
    assert history_gate(long_h1, long_h4).sufficient


def test_ambiguity_policy_is_explicit() -> None:
    assert AmbiguityPolicy.ADVERSE.value == BacktestConfig().ambiguity_policy


def fake_analysis(symbol: str, h1: object, h4: object, evaluation_time: datetime,
                  config: AnalysisConfig) -> AnalysisResult:
    """Small deterministic Layer 3 stand-in used only to isolate replay boundary tests."""
    item = candidate(evaluation=evaluation_time)
    item = replace(item, candidate_id=evaluation_time.isoformat(),
                   evaluation_id=evaluation_time.isoformat(),
                   parameter_version=config.parameter_version)
    snapshot = AnalysisSnapshot(
        item.evaluation_id, symbol, evaluation_time, evaluation_time,
        evaluation_time - timedelta(hours=1), evaluation_time - timedelta(hours=4),
        config.strategy_version, config.parameter_version, MappingProxyType({}), item.h4_regime,
        MappingProxyType({}), True, item.side, item.setup_type, item.trade_style, "test", (), (),
        None, item.session_context, item.volatility_context, item.macro_context,
    )
    return AnalysisResult(snapshot, item)


def test_training_target_inside_test_is_censored_not_scored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forex.backtest.analyse_market", fake_analysis)
    h1 = [candle(0, open_=1, high=1.05, low=.95, close=1),
          candle(1, open_=1, high=1.05, low=.95, close=1),
          candle(2, open_=1, high=1.05, low=.95, close=1),
          candle(3, open_=1, high=1.2, low=.95, close=1.15)]
    boundary = START + timedelta(hours=3)
    result = run_backtest("EURUSD", h1, [candle(0, Timeframe.H4)], AnalysisConfig(),
                          BacktestConfig(simulation_horizon_bars=10, breakeven_at_r=None),
                          POLICY,
                          evaluation_start_utc=START + timedelta(hours=1),
                          evaluation_end_utc=boundary, outcome_end_utc=boundary)
    assert not result.trades
    assert result.metrics.gross.expectancy_r is None
    assert result.metrics.simulation_status_counts == {"WINDOW_BOUNDARY_CENSORED": 2}


def test_test_price_mutation_cannot_change_training_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forex.backtest.analyse_market", fake_analysis)
    base = [candle(i, open_=1, high=1.05, low=.95, close=1) for i in range(8)]
    changed = list(base)
    changed[4] = candle(4, open_=2, high=3, low=1, close=2.5)
    boundary = START + timedelta(hours=4)
    arguments = ("EURUSD", base, [candle(0, Timeframe.H4)], AnalysisConfig(),
                 BacktestConfig(simulation_horizon_bars=10, breakeven_at_r=None), POLICY)
    before = run_backtest(*arguments, evaluation_start_utc=START + timedelta(hours=1),
                          evaluation_end_utc=boundary, outcome_end_utc=boundary)
    after = run_backtest(arguments[0], changed, *arguments[2:],
                         evaluation_start_utc=START + timedelta(hours=1),
                         evaluation_end_utc=boundary, outcome_end_utc=boundary)
    assert before.metrics == after.metrics


def test_test_outcomes_and_forward_paths_do_not_cross_test_end(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forex.backtest.analyse_market", fake_analysis)
    h1 = [candle(i, open_=1, high=1.05, low=.95, close=1) for i in range(6)]
    h1[4] = candle(4, open_=1, high=1.2, low=.95, close=1.15)
    boundary = START + timedelta(hours=4)
    result = run_backtest("EURUSD", h1, [candle(0, Timeframe.H4)], AnalysisConfig(),
                          BacktestConfig(forward_horizons_bars=[5], simulation_horizon_bars=10,
                                         breakeven_at_r=None),
                          POLICY,
                          evaluation_start_utc=START + timedelta(hours=2),
                          evaluation_end_utc=boundary, outcome_end_utc=boundary)
    changed = list(h1)
    changed[4] = candle(4, open_=2, high=3, low=1, close=2.5)
    changed_result = run_backtest(
        "EURUSD", changed, [candle(0, Timeframe.H4)], AnalysisConfig(),
        BacktestConfig(forward_horizons_bars=[5], simulation_horizon_bars=10,
                       breakeven_at_r=None), POLICY,
        evaluation_start_utc=START + timedelta(hours=2),
        evaluation_end_utc=boundary, outcome_end_utc=boundary,
    )
    assert [item.forward_paths for item in result.evaluations] == [
        item.forward_paths for item in changed_result.evaluations
    ]
    assert not result.trades
    assert all(attempt.status is SimulationStatus.WINDOW_BOUNDARY_CENSORED
               for attempt in result.simulation_attempts)


def test_final_holdout_mutation_cannot_change_folds_or_selection(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forex.backtest.analyse_market", fake_analysis)
    h1 = [candle(i, open_=1, high=1.2, low=.95, close=1.15) for i in range(24 * 12)]
    h4 = [candle(i, Timeframe.H4) for i in range(24 * 12 // 4)]
    config = BacktestConfig(train_days=3, test_days=2, step_days=2, final_holdout_days=2,
                            simulation_horizon_bars=1, breakeven_at_r=None,
                            forward_horizons_bars=[1])
    experiments = [parameter_experiment(AnalysisConfig(), {"rsi_period": value})
                   for value in (10, 12)]
    before = run_walk_forward("EURUSD", h1, h4, experiments, config, POLICY)
    changed = list(h1)
    holdout_start = before.final_holdout_start_utc
    assert holdout_start is not None
    changed = [candle(index, open_=2, high=3, low=1, close=2.5)
               if item.timestamp_utc >= holdout_start else item
               for index, item in enumerate(changed)]
    after = run_walk_forward("EURUSD", changed, h4, experiments, config, POLICY)
    assert before == after


def test_setup_episode_metrics_preserve_every_candidate_evaluation(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("forex.backtest.analyse_market", fake_analysis)
    result = run_backtest(
        "EURUSD", [candle(i) for i in range(5)], [candle(0, Timeframe.H4)], AnalysisConfig(),
        BacktestConfig(simulation_horizon_bars=1, breakeven_at_r=None), POLICY,
    )
    assert result.metrics.candidate_count == 5
    assert result.metrics.setup_episode_count == 1
    assert result.metrics.average_candidate_evaluations_per_episode == 5
    assert result.metrics.median_candidate_evaluations_per_episode == 5


def test_simulation_drop_off_reasons_are_explicit() -> None:
    no_bar = simulate_trade_attempt(candidate(), [], BacktestConfig())
    invalid = simulate_trade_attempt(candidate(), [candle(0, open_=.8, high=.85, low=.75,
                                                          close=.8)], BacktestConfig())
    censored = simulate_trade_attempt(
        candidate(), [candle(0)], BacktestConfig(simulation_horizon_bars=2),
        outcome_end_utc=START + timedelta(hours=1),
    )
    assert no_bar.status is SimulationStatus.NO_NEXT_BAR
    assert invalid.status is SimulationStatus.NON_POSITIVE_INITIAL_RISK
    assert censored.status is SimulationStatus.WINDOW_BOUNDARY_CENSORED
