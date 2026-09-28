from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from forex.analysis import (Availability, RegimeLabel, RegimeState, RelativeMacroContext,
                            SetupType, Side, TradeCandidate, TradeStyle)
from forex.domain import AccountMode, AccountState, SymbolSpec
from forex.persistence import RiskSessionStore
from forex.risk import (ContextualConviction, DailyRiskState, DecisionStatus, OpenRiskPosition,
                        PortfolioRiskState, RiskBlockReason, derive_conviction, decide_risk,
                        enforce_layer6_ceiling, evaluate_daily_risk, exposure_diagnostics,
                        protective_stop, risk_tier, size_position)

D = Decimal
NOW = datetime(2026, 1, 2, tzinfo=UTC)


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
    values = dict(requested_name="EURUSD", broker_name="EURUSD", base_currency="EUR",
                  profit_currency="USD", digits=5, point=D(".00001"), tick_size=D(".00001"),
                  tick_value=D("1"), contract_size=D("100000"), volume_min=D(".01"),
                  volume_max=D("100"), volume_step=D(".01"), stops_level_points=10,
                  freeze_level_points=0, filling_mode=0)
    values.update(updates)
    return SymbolSpec(**values)


@pytest.mark.parametrize(("score", "band", "risk"), [(D("54.999"), "BELOW_55", None),
    (D("55"), "55_TO_69", D(".02")), (D("70"), "70_TO_84", D(".035")),
    (D("85"), "85_TO_100", D(".05")), (D("100"), "85_TO_100", D(".05"))])
def test_operator_tier_boundaries(score: Decimal, band: str, risk: Decimal | None) -> None:
    result = risk_tier(score)
    assert result.band.value == band and result.risk_percent == risk


def test_conviction_preserves_layer3_score_is_deterministic_and_unavailable_is_neutral() -> None:
    item = candidate(.3)
    plain = derive_conviction(item)
    unavailable = derive_conviction(item, (ContextualConviction("macro", Availability.UNAVAILABLE),))
    assert plain == derive_conviction(item)
    assert plain.technical_conviction == D("70") == unavailable.final_conviction
    assert unavailable.eligible  # unavailable is neither zero nor a unanimity veto
    assert plain.strategy_version == "layer3-v1"


def test_available_context_is_graded_not_unanimity() -> None:
    result = derive_conviction(candidate(.2),
        (ContextualConviction("fixture", Availability.AVAILABLE, D("20"), D(".1")),))
    assert D("55") < result.final_conviction < D("80") and result.eligible
    with pytest.raises(ValueError):
        risk_tier(D("101"))


def test_long_short_dynamic_tick_sizing_rounds_down_and_never_exceeds_budget() -> None:
    long, errors = size_position(account(), spec(tick_size=D(".00002"), tick_value=D("2")),
                                 Side.LONG, D("1.10000"), D("1.09701"), D(".02"))
    short, _ = size_position(account(), spec(), Side.SHORT, D("1.10000"), D("1.10299"), D(".02"))
    assert not errors and long and short
    assert long.volume == D(".66")  # Decimal floor, never binary-float or round-up
    assert long.actual_risk_amount <= long.requested_risk_amount
    assert short.actual_risk_amount <= short.requested_risk_amount


def test_volume_min_rejection_and_max_cap() -> None:
    plan, reasons = size_position(account("100"), spec(volume_min=D(".1")), Side.LONG,
                                  D("1.1"), D("1.09"), D(".02"))
    assert plan is None and reasons == (RiskBlockReason.VOLUME_BELOW_MINIMUM,)
    capped, _ = size_position(account("1000000"), spec(volume_max=D("1")), Side.LONG,
                              D("1.1"), D("1.09"), D(".05"))
    assert capped and capped.volume == D("1")


@pytest.mark.parametrize(("kwargs", "reason"), [
    ({"tick_size": D("0")}, RiskBlockReason.INVALID_SYMBOL_SPEC),
    ({"tick_value": D("-1")}, RiskBlockReason.INVALID_SYMBOL_SPEC)])
def test_invalid_runtime_tick_properties(kwargs: dict[str, object], reason: RiskBlockReason) -> None:
    assert size_position(account(), spec(**kwargs), Side.LONG, D("1.1"), D("1.09"), D(".02"))[1] == (reason,)


def test_stop_side_minimum_distance_and_leverage_guards() -> None:
    assert size_position(account(), spec(), Side.LONG, D("1.1"), D("1.1"), D(".02"))[1] == (RiskBlockReason.INVALID_STOP_SIDE,)
    assert size_position(account(), spec(stops_level_points=20), Side.LONG, D("1.1"), D("1.0999"), D(".02"))[1] == (RiskBlockReason.STOP_TOO_CLOSE,)
    assert size_position(account(leverage=31), spec(), Side.LONG, D("1.1"), D("1.09"), D(".02"))[1] == (RiskBlockReason.INVALID_LEVERAGE,)


def test_minimum_objective_and_rr_floor_long_and_short() -> None:
    long, _ = size_position(account(), spec(), Side.LONG, D("1.1"), D("1.09"), D(".02"), D("1.115"))
    short, _ = size_position(account(), spec(), Side.SHORT, D("1.1"), D("1.11"), D(".02"), D("1.085"))
    assert long and long.minimum_objective == D("1.115")
    assert short and short.minimum_objective == D("1.085")
    assert size_position(account(), spec(), Side.LONG, D("1.1"), D("1.09"), D(".02"), D("1.1149"))[1] == (RiskBlockReason.REWARD_RISK_BELOW_1_5,)


def position(stop: str = "1.09", symbol: str = "EURUSD", side: Side = Side.LONG,
             volume: str = "1") -> OpenRiskPosition:
    return OpenRiskPosition(symbol, side, D("1.1"), D(stop), D(volume), D(".00001"), D("1"))


def decision(portfolio: PortfolioRiskState = PortfolioRiskState(()), balance: str = "10000"):
    return decide_risk(candidate(.15), account(balance), spec(), D("1.1"), D("1.09"), None,
                       portfolio, DailyRiskState("session", D(balance), D(balance)))


def test_portfolio_zero_exact_limit_over_limit_and_four_positions() -> None:
    assert decision().status is DecisionStatus.ELIGIBLE
    exact = PortfolioRiskState((position(volume="1.5"),))  # 1500 + 500 proposal = 20%
    assert decision(exact).status is DecisionStatus.ELIGIBLE
    over = PortfolioRiskState((position(volume="1.51"),))
    assert decision(over).reasons == (RiskBlockReason.PORTFOLIO_RISK,)
    four = PortfolioRiskState((position(stop="1.1"),) * 4)
    assert decision(four).reasons == (RiskBlockReason.MAX_POSITIONS,)


def test_protected_position_zero_floor_and_usd_concentration_is_diagnostic_only() -> None:
    positions = (position(stop="1.1"), position(stop="1.11"))
    assert PortfolioRiskState(positions).existing_risk == 0
    diagnostic = exposure_diagnostics((position(),), "GBPUSD", Side.LONG, D("100"))
    assert diagnostic.same_direction_usd_concentration > 0
    assert not diagnostic.correlation_veto_applied


@pytest.mark.parametrize(("equity", "active"), [("8801", False), ("8800", True), ("8700", True)])
def test_circuit_breaker_boundary(equity: str, active: bool) -> None:
    result = evaluate_daily_risk(DailyRiskState("s", D("10000"), D(equity)))
    assert result.circuit_breaker_active is active
    assert result.flatten_required is active


def test_circuit_latches_recovery_new_session_and_kill_switch_distinction() -> None:
    latched = evaluate_daily_risk(DailyRiskState("day1", D("100"), D("100"), True))
    reset = evaluate_daily_risk(DailyRiskState("day2", D("100"), D("100")))
    killed = evaluate_daily_risk(DailyRiskState("day2", D("100"), D("100"), False, True))
    assert latched.circuit_breaker_active and not reset.circuit_breaker_active
    assert killed.reasons == (RiskBlockReason.KILL_SWITCH,) and killed.flatten_required
    halted = decide_risk(candidate(), account(), spec(), D("1.1"), D("1.09"), None,
                          PortfolioRiskState(()), DailyRiskState("s", D("10000"), D("8700")))
    assert halted.status is DecisionStatus.HALT_FLATTEN_REQUIRED


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
        store.save(DailyRiskState("x", D("1"), D("1")), datetime(2026, 1, 1))


def test_layer6_contract_cannot_enlarge_volume_or_loosen_stop() -> None:
    plan, _ = size_position(account(), spec(), Side.LONG, D("1.1"), D("1.09"), D(".02"))
    assert plan is not None
    assert enforce_layer6_ceiling(plan, plan.volume / 2, D("1.095"), Side.LONG)
    assert not enforce_layer6_ceiling(plan, plan.volume + D(".01"), plan.stop, Side.LONG)
    assert not enforce_layer6_ceiling(plan, plan.volume, D("1.089"), Side.LONG)


def test_pure_risk_module_has_no_execution_io_clock_or_network_calls() -> None:
    source = Path("src/forex/risk.py").read_text(encoding="utf-8")
    forbidden = ("order_send", "place_order", "modify_position", "close_position",
                 "datetime.now", "sqlite3", "httpx", "MetaTrader5")
    assert all(name not in source for name in forbidden)


def test_layer4_imports_shared_layer5_conviction_logic() -> None:
    source = Path("src/forex/backtest.py").read_text(encoding="utf-8")
    assert "from forex.risk import ConvictionBand, derive_conviction" in source
    assert "derive_conviction(candidate)" in source
