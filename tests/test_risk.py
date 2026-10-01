from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from forex.analysis import (
    Availability,
    RegimeLabel,
    RegimeState,
    RelativeMacroContext,
    SetupType,
    Side,
    TradeCandidate,
    TradeStyle,
)
from forex.config import RiskConfig, load_config
from forex.domain import AccountMode, AccountState, SymbolSpec
from forex.persistence import RiskSessionStore
from forex.risk import (
    RISK_POLICY_IMPLEMENTATION_VERSION,
    ContextualConviction,
    DailyRiskState,
    DecisionStatus,
    OpenRiskPosition,
    PortfolioRiskState,
    RiskBlockReason,
    RiskPolicy,
    decide_risk,
    derive_conviction,
    enforce_layer6_ceiling,
    evaluate_daily_risk,
    exposure_diagnostics,
    protective_stop,
    risk_tier,
    size_position,
)
from forex.risk_policy import policy_from_config

D = Decimal
NOW = datetime(2026, 1, 2, tzinfo=UTC)

POLICY = RiskPolicy(30, D("1.5"), 4, D(".20"), D(".12"),
                    D("55"), D("70"), D("85"), D(".02"), D(".035"), D(".05"))


def candidate(uncertainty: float = .2, side: Side = Side.LONG) -> TradeCandidate:
    regime = RegimeState(RegimeLabel.TREND_UP, .8, .8, .2, .4, .5, .2)
    return TradeCandidate("candidate", "evaluation", "EURUSD", NOW, NOW, side,
                          SetupType.TREND_CONTINUATION, TradeStyle.DAY, "fixture",
                          "layer3-v1", "unvalidated-v1", regime, .8,
                          MappingProxyType({"score": 1 - uncertainty}), .4,
                          MappingProxyType({}), (), (), uncertainty,
                          MappingProxyType({"rolling_low": 1.09, "rolling_high": 1.11}),
                          MappingProxyType({"h1_atr": .001}),
                          RelativeMacroContext.unavailable("EURUSD"), ("LONDON",))


def account(balance: str = "10000", leverage: int = 30) -> AccountState:
    return AccountState(1, "AUD", D(balance), D(balance), leverage, AccountMode.HEDGING)


def spec(**updates: object) -> SymbolSpec:
    values = {"requested_name": "EURUSD", "broker_name": "EURUSD", "base_currency": "EUR",
              "profit_currency": "USD", "digits": 5, "point": D(".00001"),
              "tick_size": D(".00001"), "tick_value": D("1"),
              "contract_size": D("100000"), "volume_min": D(".01"),
              "volume_max": D("100"), "volume_step": D(".01"),
              "stops_level_points": 10, "freeze_level_points": 0, "filling_mode": 0}
    values.update(updates)
    return SymbolSpec(**values)


@pytest.mark.parametrize(("score", "band", "risk"), [(D("54.999"), "BELOW_MINIMUM", None),
    (D("55"), "LOW", D(".02")), (D("70"), "MEDIUM", D(".035")),
    (D("85"), "HIGH", D(".05")), (D("100"), "HIGH", D(".05"))])
def test_operator_tier_boundaries(score: Decimal, band: str, risk: Decimal | None) -> None:
    result = risk_tier(score, POLICY)
    assert result.band.value == band and result.risk_percent == risk


def test_conviction_preserves_layer3_score_is_deterministic_and_unavailable_is_neutral() -> None:
    item = candidate(.3)
    plain = derive_conviction(item, POLICY)
    unavailable = derive_conviction(item, POLICY, (ContextualConviction("macro", Availability.UNAVAILABLE),))
    assert plain == derive_conviction(item, POLICY)
    assert plain.technical_conviction == D("70") == unavailable.final_conviction
    assert unavailable.eligible  # unavailable is neither zero nor a unanimity veto
    assert plain.strategy_version == "layer3-v1"


def test_available_context_is_graded_not_unanimity() -> None:
    result = derive_conviction(candidate(.2), POLICY,
        (ContextualConviction("fixture", Availability.AVAILABLE, D("20"), D(".1")),))
    assert D("55") < result.final_conviction < D("80") and result.eligible
    with pytest.raises(ValueError):
        risk_tier(D("101"), POLICY)


# The operator's aggressive paper profile in config.yaml (2026-10-01); POLICY stays the fixture.
OPERATOR_POLICY = replace(POLICY, daily_loss_limit=D(".25"), minimum_conviction=D("0"),
                          low_risk_percent=D(".05"), medium_risk_percent=D(".05"))


def test_config_is_exact_policy_source_and_changed_policy_changes_calculation() -> None:
    configured = policy_from_config(load_config(Path("config.yaml")).risk)
    assert configured == OPERATOR_POLICY
    changed = RiskPolicy(20, D("2"), 2, D(".10"), D(".05"),
                         D("60"), D("75"), D("90"), D(".01"), D(".02"), D(".03"))
    assert risk_tier(D("55"), changed).risk_percent is None
    assert risk_tier(D("60"), changed).risk_percent == D(".01")
    assert evaluate_daily_risk(DailyRiskState("s", D("100"), D("94")), changed).flatten_required


def test_policy_id_is_content_addressed_and_covers_material_policy_values() -> None:
    reconstructed = RiskPolicy(
        max_leverage=30,
        minimum_reward_risk=D("1.500"),
        max_concurrent_positions=4,
        max_simultaneous_risk=D("0.200"),
        daily_loss_limit=D("0.120"),
        minimum_conviction=D("55.0"),
        medium_conviction=D("70.00"),
        high_conviction=D("85"),
        low_risk_percent=D("0.020"),
        medium_risk_percent=D("0.0350"),
        high_risk_percent=D("0.050"),
    )
    assert POLICY.policy_id == POLICY.policy_id
    assert reconstructed.policy_id == POLICY.policy_id
    assert POLICY.policy_id.startswith(f"{RISK_POLICY_IMPLEMENTATION_VERSION}-")
    assert replace(POLICY, minimum_conviction=D("54")).policy_id != POLICY.policy_id
    assert replace(POLICY, low_risk_percent=D(".021")).policy_id != POLICY.policy_id
    assert replace(POLICY, minimum_reward_risk=D("1.6")).policy_id != POLICY.policy_id
    assert replace(POLICY, max_simultaneous_risk=D(".19")).policy_id != POLICY.policy_id


def test_config_policy_values_and_decision_identity_remain_exact_and_traceable() -> None:
    configured = policy_from_config(load_config(Path("config.yaml")).risk)
    assert configured == OPERATOR_POLICY
    assert (configured.minimum_conviction, configured.medium_conviction,
            configured.high_conviction) == (D("0"), D("70"), D("85"))
    assert (configured.low_risk_percent, configured.medium_risk_percent,
            configured.high_risk_percent) == (D(".05"), D(".05"), D(".05"))
    assert configured.minimum_reward_risk == D("1.5")
    assert configured.max_concurrent_positions == 4
    assert configured.max_simultaneous_risk == D(".20")
    assert configured.daily_loss_limit == D(".25")
    assert configured.max_leverage == 30

    first = decision()
    second = decision()
    assert first.risk_policy_id == POLICY.policy_id
    assert first.risk_policy_implementation_version == RISK_POLICY_IMPLEMENTATION_VERSION
    assert first.decision_id == second.decision_id

    changed = replace(POLICY, minimum_conviction=D("54"))
    changed_decision = decide_risk(
        candidate(.15), account(), spec(), D("1.1"), D("1.09"), None,
        PortfolioRiskState(()), DailyRiskState("session", D("10000"), D("10000")),
        changed,
    )
    assert changed_decision.risk_policy_id == changed.policy_id
    assert changed_decision.risk_policy_id != first.risk_policy_id
    assert changed_decision.decision_id != first.decision_id


def test_risk_config_validates_threshold_order_and_tier_mapping() -> None:
    raw = load_config(Path("config.yaml")).risk.model_dump()
    with pytest.raises(ValueError, match="minimum < medium < high"):
        RiskConfig.model_validate({**raw, "conviction_thresholds": {
            "minimum": 70, "medium": 55, "high": 85}})
    with pytest.raises(ValueError, match="exactly low, medium, high"):
        RiskConfig.model_validate({**raw, "conviction_risk_percent": {"low": 2}})
    with pytest.raises(ValueError, match="non-decreasing"):
        RiskConfig.model_validate({**raw, "conviction_risk_percent": {
            "low": 5, "medium": 3.5, "high": 2}})


def test_long_short_dynamic_tick_sizing_rounds_down_and_never_exceeds_budget() -> None:
    long, errors = size_position(account(), spec(tick_size=D(".00002"), tick_value=D("2")),
                                 Side.LONG, D("1.10000"), D("1.09701"), D(".02"), POLICY)
    short, _ = size_position(account(), spec(), Side.SHORT, D("1.10000"), D("1.10299"), D(".02"), POLICY)
    assert not errors and long and short
    assert long.volume == D(".66")  # Decimal floor, never binary-float or round-up
    assert long.actual_risk_amount <= long.requested_risk_amount
    assert short.actual_risk_amount <= short.requested_risk_amount


def test_volume_min_rejection_and_max_cap() -> None:
    plan, reasons = size_position(account("100"), spec(volume_min=D(".1")), Side.LONG,
                                  D("1.1"), D("1.09"), D(".02"), POLICY)
    assert plan is None and reasons == (RiskBlockReason.VOLUME_BELOW_MINIMUM,)
    capped, _ = size_position(account("1000000"), spec(volume_max=D("1")), Side.LONG,
                              D("1.1"), D("1.09"), D(".05"), POLICY)
    assert capped and capped.volume == D("1")


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({"tick_size": D("0")}, RiskBlockReason.INVALID_SYMBOL_SPEC),
    ({"tick_value": D("-1")}, RiskBlockReason.INVALID_SYMBOL_SPEC)])
def test_invalid_runtime_tick_properties(kwargs: dict[str, object], reason: RiskBlockReason) -> None:
    assert size_position(account(), spec(**kwargs), Side.LONG, D("1.1"), D("1.09"), D(".02"), POLICY)[1] == (reason,)


def test_stop_side_minimum_distance_and_leverage_guards() -> None:
    assert size_position(account(), spec(), Side.LONG, D("1.1"), D("1.1"), D(".02"), POLICY)[1] == (RiskBlockReason.INVALID_STOP_SIDE,)
    assert size_position(account(), spec(stops_level_points=20), Side.LONG, D("1.1"), D("1.0999"), D(".02"), POLICY)[1] == (RiskBlockReason.STOP_TOO_CLOSE,)
    assert size_position(account(leverage=31), spec(), Side.LONG, D("1.1"), D("1.09"), D(".02"), POLICY)[1] == (RiskBlockReason.INVALID_LEVERAGE,)


def test_minimum_objective_and_rr_floor_long_and_short() -> None:
    long, _ = size_position(account(), spec(), Side.LONG, D("1.1"), D("1.09"), D(".02"), POLICY, D("1.115"))
    short, _ = size_position(account(), spec(), Side.SHORT, D("1.1"), D("1.11"), D(".02"), POLICY, D("1.085"))
    assert long and long.minimum_objective == D("1.115")
    assert short and short.minimum_objective == D("1.085")
    assert size_position(account(), spec(), Side.LONG, D("1.1"), D("1.09"), D(".02"), POLICY, D("1.1149"))[1] == (RiskBlockReason.REWARD_RISK_BELOW_1_5,)


def position(stop: str = "1.09", symbol: str = "EURUSD", side: Side = Side.LONG,
             volume: str = "1") -> OpenRiskPosition:
    return OpenRiskPosition(symbol, side, D("1.1"), D(stop), D(volume), D(".00001"), D("1"))


def decision(portfolio: PortfolioRiskState | None = None, balance: str = "10000"):
    if portfolio is None:
        portfolio = PortfolioRiskState(())
    return decide_risk(candidate(.15), account(balance), spec(), D("1.1"), D("1.09"), None,
                       portfolio, DailyRiskState("session", D(balance), D(balance)), POLICY)


def test_portfolio_zero_exact_limit_over_limit_and_four_positions() -> None:
    assert decision().status is DecisionStatus.ELIGIBLE
    assert decision().permitted_position_plan is not None
    exact = PortfolioRiskState((position(volume="1.5"),))  # 1500 + 500 proposal = 20%
    assert decision(exact).status is DecisionStatus.ELIGIBLE
    over = PortfolioRiskState((position(volume="1.51"),))
    assert decision(over).reasons == (RiskBlockReason.PORTFOLIO_RISK,)
    assert decision(over).permitted_position_plan is None
    four = PortfolioRiskState((position(stop="1.1"),) * 4)
    assert decision(four).reasons == (RiskBlockReason.MAX_POSITIONS,)
    assert decision(four).permitted_position_plan is None


def test_protected_position_zero_floor_and_usd_concentration_is_diagnostic_only() -> None:
    positions = (position(stop="1.1"), position(stop="1.11"))
    assert PortfolioRiskState(positions).existing_risk == 0
    diagnostic = exposure_diagnostics((position(),), "GBPUSD", Side.LONG, D("100"))
    assert diagnostic.same_direction_usd_concentration > 0
    assert not diagnostic.correlation_veto_applied


@pytest.mark.parametrize(("equity", "active"), [("8801", False), ("8800", True), ("8700", True)])
def test_circuit_breaker_boundary(equity: str, active: bool) -> None:
    result = evaluate_daily_risk(DailyRiskState("s", D("10000"), D(equity)), POLICY)
    assert result.circuit_breaker_active is active
    assert result.flatten_required is active


def test_circuit_latches_recovery_new_session_and_kill_switch_distinction() -> None:
    latched = evaluate_daily_risk(DailyRiskState("day1", D("100"), D("100"), True), POLICY)
    reset = evaluate_daily_risk(DailyRiskState("day2", D("100"), D("100")), POLICY)
    killed = evaluate_daily_risk(DailyRiskState("day2", D("100"), D("100"), False, True), POLICY)
    assert latched.circuit_breaker_active and not reset.circuit_breaker_active
    assert killed.reasons == (RiskBlockReason.KILL_SWITCH,) and killed.flatten_required
    halted = decide_risk(candidate(), account(), spec(), D("1.1"), D("1.09"), None,
                          PortfolioRiskState(()), DailyRiskState("s", D("10000"), D("8700")), POLICY)
    assert halted.status is DecisionStatus.HALT_FLATTEN_REQUIRED
    assert halted.permitted_position_plan is None
    killed_decision = decide_risk(
        candidate(), account(), spec(), D("1.1"), D("1.09"), None, PortfolioRiskState(()),
        DailyRiskState("s", D("10000"), D("10000"), False, True), POLICY)
    assert killed_decision.permitted_position_plan is None
    ineligible = decide_risk(
        candidate(.5), account(), spec(), D("1.1"), D("1.09"), None,
        PortfolioRiskState(()), DailyRiskState("s", D("10000"), D("10000")), POLICY)
    assert ineligible.status is DecisionStatus.SIGNAL_NOT_ELIGIBLE
    assert ineligible.permitted_position_plan is None


def test_breakeven_then_atr_trailing_and_never_loosen() -> None:
    waiting = protective_stop(Side.LONG, D("1.1"), D("1.09"), D("1.095"), D("1.109"), D(".002"), D("2"))
    assert waiting.stop == D("1.095") and not waiting.trailing_applied
    unconfigured = protective_stop(Side.LONG, D("1.1"), D("1.09"), D("1.095"), D("1.11"), D(".002"), None)
    assert unconfigured.stop == D("1.1") and unconfigured.atr_trailing_status == "UNVALIDATED_NOT_CONFIGURED"
    trailed = protective_stop(Side.LONG, D("1.1"), D("1.09"), D("1.1"), D("1.12"), D(".002"), D("2"))
    assert trailed.stop == D("1.116")
    short = protective_stop(Side.SHORT, D("1.1"), D("1.11"), D("1.1"), D("1.08"), D(".002"), D("2"))
    assert short.stop == D("1.084")


def test_risk_session_persistence_latches_and_requires_utc(tmp_path: Path) -> None:
    store = RiskSessionStore(tmp_path / "risk.sqlite")
    store.save(DailyRiskState("day", D("100"), D("87"), True, True), NOW, NOW)
    loaded = store.load("day", D("99"))
    assert loaded and loaded.circuit_breaker_triggered and loaded.kill_switch_active
    store.save(DailyRiskState("day", D("100"), D("99"), False, False), NOW)
    reloaded = store.load("day", D("99"))
    assert reloaded and reloaded.circuit_breaker_triggered and not reloaded.kill_switch_active
    with pytest.raises(ValueError):
        store.save(DailyRiskState("x", D("1"), D("1")), NOW.replace(tzinfo=None))


def test_session_first_opening_balance_is_authoritative(tmp_path: Path) -> None:
    store = RiskSessionStore(tmp_path / "risk.sqlite")
    store.save(DailyRiskState("day1", D("10000"), D("10000")), NOW)
    store.save(DailyRiskState("day1", D("9000"), D("9000"), True), NOW, NOW)
    day1 = store.load("day1", D("9000"))
    assert day1 and day1.opening_balance == D("10000") and day1.circuit_breaker_triggered
    store.save(DailyRiskState("day2", D("9000"), D("9000")), NOW)
    day2 = store.load("day2", D("9000"))
    assert day2 and day2.opening_balance == D("9000")


def test_layer6_contract_cannot_enlarge_volume_or_loosen_stop() -> None:
    plan, _ = size_position(account(), spec(), Side.LONG, D("1.1"), D("1.09"), D(".02"), POLICY)
    assert plan is not None
    assert enforce_layer6_ceiling(
        plan, plan.volume / 2, D("1.095"), plan.minimum_objective, Side.LONG)
    assert not enforce_layer6_ceiling(
        plan, plan.volume + D(".01"), plan.stop, plan.minimum_objective, Side.LONG)
    assert not enforce_layer6_ceiling(
        plan, plan.volume, D("1.089"), plan.minimum_objective, Side.LONG)
    assert not enforce_layer6_ceiling(
        plan, plan.volume, plan.stop, plan.minimum_objective - D(".00001"), Side.LONG)
    short, _ = size_position(
        account(), spec(), Side.SHORT, D("1.1"), D("1.11"), D(".02"), POLICY)
    assert short is not None
    assert not enforce_layer6_ceiling(
        short, short.volume, short.stop, short.minimum_objective + D(".00001"), Side.SHORT)


def test_decision_id_canonicalizes_equivalent_portfolio_order() -> None:
    first = position(symbol="EURUSD", volume=".1")
    second = position(symbol="GBPUSD", side=Side.SHORT, stop="1.11", volume=".1")
    assert decision(PortfolioRiskState((first, second))).decision_id == decision(
        PortfolioRiskState((second, first))).decision_id


def test_pure_risk_module_has_no_execution_io_clock_or_network_calls() -> None:
    source = Path("src/forex/risk.py").read_text(encoding="utf-8")
    forbidden = ("order_send", "place_order", "modify_position", "close_position",
                 "datetime.now", "sqlite3", "httpx", "MetaTrader5")
    assert all(name not in source for name in forbidden)


def test_layer4_imports_shared_layer5_conviction_logic() -> None:
    source = Path("src/forex/backtest.py").read_text(encoding="utf-8")
    assert "derive_conviction(candidate, policy)" in source
