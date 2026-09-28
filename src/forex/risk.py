"""Pure Layer 5 conviction, exposure, and protective-management policy.

No function in this module reads a clock, database, broker, network, or mutable global.
The constants are versioned operator policy, not empirically validated parameters.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from enum import Enum

from forex.analysis import Availability, Evidence, Side, TradeCandidate
from forex.domain import AccountState, SymbolSpec

FUSION_POLICY_VERSION = "layer5-fusion-v1-unvalidated"
RISK_POLICY_VERSION = "layer5-risk-v1-operator"
MINIMUM_REWARD_RISK = Decimal("1.5")
MAX_POSITIONS = 4
MAX_SIMULTANEOUS_RISK = Decimal("0.20")
DAILY_LOSS_LIMIT = Decimal("0.12")
MAX_LEVERAGE = 30


class ConvictionBand(str, Enum):
    BELOW_THRESHOLD = "BELOW_55"
    RISK_2_PERCENT = "55_TO_69"
    RISK_3_5_PERCENT = "70_TO_84"
    RISK_5_PERCENT = "85_TO_100"


class DecisionStatus(str, Enum):
    SIGNAL_NOT_ELIGIBLE = "SIGNAL_NOT_ELIGIBLE"
    HARD_RISK_BLOCK = "HARD_RISK_BLOCK"
    HALT_FLATTEN_REQUIRED = "HALT_FLATTEN_REQUIRED"
    ELIGIBLE = "ELIGIBLE"


class RiskBlockReason(str, Enum):
    CONVICTION_BELOW_55 = "CONVICTION_BELOW_PROVISIONAL_55"
    INVALID_LEVERAGE = "ACCOUNT_LEVERAGE_EXCEEDS_1_TO_30"
    INVALID_STOP_SIDE = "STRUCTURAL_STOP_ON_WRONG_SIDE"
    STOP_TOO_CLOSE = "BROKER_MINIMUM_STOP_DISTANCE_VIOLATED"
    INVALID_SYMBOL_SPEC = "INVALID_TICK_OR_VOLUME_PROPERTIES"
    VOLUME_BELOW_MINIMUM = "BROKER_MINIMUM_VOLUME_EXCEEDS_RISK_BUDGET"
    REWARD_RISK_BELOW_1_5 = "OBJECTIVE_BELOW_1_5R"
    MAX_POSITIONS = "MAXIMUM_FOUR_OPEN_POSITIONS"
    PORTFOLIO_RISK = "MAXIMUM_20_PERCENT_SIMULTANEOUS_RISK"
    CIRCUIT_BREAKER = "DAILY_12_PERCENT_CIRCUIT_BREAKER"
    KILL_SWITCH = "KILL_SWITCH_ACTIVE"


@dataclass(frozen=True)
class ContextualConviction:
    source: str
    availability: Availability
    conviction: Decimal | None = None
    confidence: Decimal | None = None


@dataclass(frozen=True)
class ConvictionResult:
    candidate_id: str
    evaluation_id: str
    strategy_version: str
    parameter_version: str
    fusion_policy_version: str
    technical_conviction: Decimal
    final_conviction: Decimal
    supporting_evidence: tuple[Evidence, ...]
    opposing_evidence: tuple[Evidence, ...]
    contextual_availability: tuple[tuple[str, Availability], ...]
    band: ConvictionBand
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RiskTier:
    band: ConvictionBand
    risk_percent: Decimal | None


@dataclass(frozen=True)
class PositionRiskPlan:
    entry: Decimal
    stop: Decimal
    minimum_objective: Decimal
    requested_objective: Decimal | None
    requested_risk_amount: Decimal
    actual_risk_amount: Decimal
    requested_risk_percent: Decimal
    actual_risk_percent: Decimal
    volume: Decimal
    stop_distance: Decimal
    loss_per_lot: Decimal


@dataclass(frozen=True)
class OpenRiskPosition:
    symbol: str
    side: Side
    entry: Decimal
    current_stop: Decimal
    volume: Decimal
    tick_size: Decimal
    tick_value: Decimal

    @property
    def remaining_risk(self) -> Decimal:
        adverse = ((self.entry - self.current_stop) if self.side is Side.LONG
                   else (self.current_stop - self.entry))
        return max(Decimal(0), adverse / self.tick_size * self.tick_value * self.volume)


@dataclass(frozen=True)
class ExposureDiagnostics:
    risk_by_symbol: tuple[tuple[str, Decimal], ...]
    currencies: tuple[str, ...]
    usd_directional_risk: tuple[tuple[str, Decimal], ...]
    same_direction_usd_concentration: Decimal
    correlation_veto_applied: bool = False


@dataclass(frozen=True)
class PortfolioRiskState:
    positions: tuple[OpenRiskPosition, ...]

    @property
    def existing_risk(self) -> Decimal:
        return sum((position.remaining_risk for position in self.positions), Decimal(0))


@dataclass(frozen=True)
class DailyRiskState:
    session_id: str
    opening_balance: Decimal
    current_equity: Decimal
    circuit_breaker_triggered: bool = False
    kill_switch_active: bool = False


@dataclass(frozen=True)
class DailyRiskResult:
    session_id: str
    loss_percent: Decimal
    circuit_breaker_active: bool
    kill_switch_active: bool
    new_entries_blocked: bool
    flatten_required: bool
    reasons: tuple[RiskBlockReason, ...]


@dataclass(frozen=True)
class ProtectiveStopResult:
    stop: Decimal
    breakeven_eligible: bool
    breakeven_applied: bool
    trailing_applied: bool
    atr_trailing_status: str


@dataclass(frozen=True)
class RiskDecision:
    decision_id: str
    status: DecisionStatus
    conviction: ConvictionResult
    tier: RiskTier
    position_plan: PositionRiskPlan | None
    existing_portfolio_risk: Decimal
    proposed_portfolio_risk: Decimal
    exposure: ExposureDiagnostics
    flatten_required: bool
    reasons: tuple[RiskBlockReason, ...]
    risk_policy_version: str = RISK_POLICY_VERSION


def risk_tier(conviction: Decimal) -> RiskTier:
    if not conviction.is_finite() or conviction < 0 or conviction > 100:
        raise ValueError("conviction must be finite and within 0..100")
    if conviction < 55:
        return RiskTier(ConvictionBand.BELOW_THRESHOLD, None)
    if conviction < 70:
        return RiskTier(ConvictionBand.RISK_2_PERCENT, Decimal("0.02"))
    if conviction < 85:
        return RiskTier(ConvictionBand.RISK_3_5_PERCENT, Decimal("0.035"))
    return RiskTier(ConvictionBand.RISK_5_PERCENT, Decimal("0.05"))


def derive_conviction(candidate: TradeCandidate,
                      contexts: tuple[ContextualConviction, ...] = ()) -> ConvictionResult:
    """Preserve Layer 3's score: ``(1 - uncertainty) * 100``; exclude unavailable context."""
    technical = (Decimal(1) - Decimal(str(candidate.uncertainty))) * 100
    if not technical.is_finite() or technical < 0 or technical > 100:
        raise ValueError("Layer 3 candidate uncertainty produces conviction outside 0..100")
    weighted = technical
    weight = Decimal(1)
    availability: list[tuple[str, Availability]] = []
    for item in contexts:
        availability.append((item.source, item.availability))
        if item.availability is not Availability.AVAILABLE:
            continue
        if item.conviction is None or item.confidence is None:
            raise ValueError("available contextual conviction requires value and confidence")
        if not Decimal(0) <= item.conviction <= Decimal(100):
            raise ValueError("contextual conviction must be within 0..100")
        if not Decimal(0) <= item.confidence <= Decimal(1):
            raise ValueError("contextual confidence must be within 0..1")
        weighted += item.conviction * item.confidence
        weight += item.confidence
    final = weighted / weight
    tier = risk_tier(final)
    reasons = (() if tier.risk_percent is not None
               else (RiskBlockReason.CONVICTION_BELOW_55.value,))
    return ConvictionResult(
        candidate.candidate_id, candidate.evaluation_id, candidate.strategy_version,
        candidate.parameter_version, FUSION_POLICY_VERSION, technical, final,
        candidate.supporting_evidence, candidate.opposing_evidence, tuple(availability),
        tier.band, tier.risk_percent is not None, reasons,
    )


def evaluate_daily_risk(state: DailyRiskState) -> DailyRiskResult:
    if state.opening_balance <= 0:
        raise ValueError("session opening balance must be positive")
    loss = max(Decimal(0), (state.opening_balance - state.current_equity)
               / state.opening_balance)
    circuit = state.circuit_breaker_triggered or loss >= DAILY_LOSS_LIMIT
    reasons: list[RiskBlockReason] = []
    if circuit:
        reasons.append(RiskBlockReason.CIRCUIT_BREAKER)
    if state.kill_switch_active:
        reasons.append(RiskBlockReason.KILL_SWITCH)
    blocked = circuit or state.kill_switch_active
    return DailyRiskResult(state.session_id, loss, circuit, state.kill_switch_active,
                           blocked, blocked, tuple(reasons))


def minimum_objective(side: Side, entry: Decimal, stop: Decimal) -> Decimal:
    distance = abs(entry - stop)
    return (entry + MINIMUM_REWARD_RISK * distance if side is Side.LONG
            else entry - MINIMUM_REWARD_RISK * distance)


def size_position(account: AccountState, spec: SymbolSpec, side: Side, entry: Decimal,
                  stop: Decimal, risk_percent: Decimal,
                  objective: Decimal | None = None) -> tuple[PositionRiskPlan | None,
                                                             tuple[RiskBlockReason, ...]]:
    if account.leverage > MAX_LEVERAGE:
        return None, (RiskBlockReason.INVALID_LEVERAGE,)
    if (side is Side.LONG and stop >= entry) or (side is Side.SHORT and stop <= entry):
        return None, (RiskBlockReason.INVALID_STOP_SIDE,)
    values = (spec.point, spec.tick_size, spec.tick_value, spec.volume_min,
              spec.volume_max, spec.volume_step)
    if any(not value.is_finite() or value <= 0 for value in values):
        return None, (RiskBlockReason.INVALID_SYMBOL_SPEC,)
    distance = abs(entry - stop)
    if distance < Decimal(spec.stops_level_points) * spec.point:
        return None, (RiskBlockReason.STOP_TOO_CLOSE,)
    min_objective = minimum_objective(side, entry, stop)
    if objective is not None:
        reward = ((objective - entry) if side is Side.LONG else (entry - objective))
        if reward / distance < MINIMUM_REWARD_RISK:
            return None, (RiskBlockReason.REWARD_RISK_BELOW_1_5,)
    loss_per_lot = distance / spec.tick_size * spec.tick_value
    budget = account.balance * risk_percent
    raw = budget / loss_per_lot
    capped = min(raw, spec.volume_max)
    volume = (capped / spec.volume_step).to_integral_value(rounding=ROUND_FLOOR) * spec.volume_step
    if volume < spec.volume_min:
        return None, (RiskBlockReason.VOLUME_BELOW_MINIMUM,)
    actual = volume * loss_per_lot
    if actual > budget:
        raise ArithmeticError("down-rounded broker volume exceeded risk budget")
    return PositionRiskPlan(entry, stop, min_objective, objective, budget, actual, risk_percent,
                            actual / account.balance, volume, distance, loss_per_lot), ()


def _usd_direction(symbol: str, side: Side) -> str | None:
    pair = symbol.upper()[:6]
    if pair[3:] == "USD":
        return "USD_SHORT" if side is Side.LONG else "USD_LONG"
    if pair[:3] == "USD":
        return "USD_LONG" if side is Side.LONG else "USD_SHORT"
    return None


def exposure_diagnostics(positions: tuple[OpenRiskPosition, ...], proposal_symbol: str | None = None,
                         proposal_side: Side | None = None,
                         proposal_risk: Decimal = Decimal(0)) -> ExposureDiagnostics:
    by_symbol: dict[str, Decimal] = {}
    usd: dict[str, Decimal] = {"USD_LONG": Decimal(0), "USD_SHORT": Decimal(0)}
    currencies: set[str] = set()
    for position in positions:
        risk = position.remaining_risk
        by_symbol[position.symbol] = by_symbol.get(position.symbol, Decimal(0)) + risk
        pair = position.symbol.upper()[:6]
        currencies.update((pair[:3], pair[3:]))
        direction = _usd_direction(position.symbol, position.side)
        if direction:
            usd[direction] += risk
    if proposal_symbol is not None and proposal_side is not None:
        by_symbol[proposal_symbol] = by_symbol.get(proposal_symbol, Decimal(0)) + proposal_risk
        pair = proposal_symbol.upper()[:6]
        currencies.update((pair[:3], pair[3:]))
        direction = _usd_direction(proposal_symbol, proposal_side)
        if direction:
            usd[direction] += proposal_risk
    return ExposureDiagnostics(tuple(sorted(by_symbol.items())), tuple(sorted(currencies)),
                               tuple(sorted(usd.items())), max(usd.values()), False)


def protective_stop(side: Side, entry: Decimal, initial_stop: Decimal,
                    current_stop: Decimal, market: Decimal, atr: Decimal,
                    atr_multiple: Decimal | None) -> ProtectiveStopResult:
    risk = abs(entry - initial_stop)
    favorable = market - entry if side is Side.LONG else entry - market
    breakeven = favorable >= risk
    stop = current_stop
    applied_be = False
    if breakeven:
        candidate = max(stop, entry) if side is Side.LONG else min(stop, entry)
        applied_be, stop = candidate != stop, candidate
    if atr_multiple is None:
        return ProtectiveStopResult(stop, breakeven, applied_be, False,
                                    "UNVALIDATED_NOT_CONFIGURED")
    if atr <= 0 or atr_multiple <= 0:
        raise ValueError("configured ATR and multiple must be positive")
    if not breakeven:
        return ProtectiveStopResult(stop, False, False, False, "WAITING_FOR_BREAKEVEN_STAGE")
    trailed = market - atr * atr_multiple if side is Side.LONG else market + atr * atr_multiple
    candidate = max(stop, trailed) if side is Side.LONG else min(stop, trailed)
    return ProtectiveStopResult(candidate, True, applied_be, candidate != stop, "CONFIGURED")


def decide_risk(candidate: TradeCandidate, account: AccountState, spec: SymbolSpec,
                entry: Decimal, stop: Decimal, objective: Decimal | None,
                portfolio: PortfolioRiskState, daily: DailyRiskState,
                contexts: tuple[ContextualConviction, ...] = ()) -> RiskDecision:
    conviction = derive_conviction(candidate, contexts)
    tier = risk_tier(conviction.final_conviction)
    daily_result = evaluate_daily_risk(daily)
    plan: PositionRiskPlan | None = None
    reasons: tuple[RiskBlockReason, ...]
    if daily_result.new_entries_blocked:
        status, reasons = DecisionStatus.HALT_FLATTEN_REQUIRED, daily_result.reasons
    elif tier.risk_percent is None:
        status, reasons = DecisionStatus.SIGNAL_NOT_ELIGIBLE, (
            RiskBlockReason.CONVICTION_BELOW_55,)
    else:
        plan, reasons = size_position(account, spec, candidate.side, entry, stop,
                                      tier.risk_percent, objective)
        status = DecisionStatus.ELIGIBLE if plan else DecisionStatus.HARD_RISK_BLOCK
        if plan is not None and len(portfolio.positions) >= MAX_POSITIONS:
            status, reasons = DecisionStatus.HARD_RISK_BLOCK, (RiskBlockReason.MAX_POSITIONS,)
        if plan is not None and portfolio.existing_risk + plan.actual_risk_amount > \
                account.balance * MAX_SIMULTANEOUS_RISK:
            status, reasons = DecisionStatus.HARD_RISK_BLOCK, (RiskBlockReason.PORTFOLIO_RISK,)
    proposal = plan.actual_risk_amount if plan else Decimal(0)
    exposure = exposure_diagnostics(portfolio.positions, candidate.symbol, candidate.side, proposal)
    stable = json.dumps({"candidate": candidate.candidate_id, "account": str(account.balance),
                         "entry": str(entry), "stop": str(stop), "objective": str(objective),
                         "session": daily.session_id, "positions": [repr(p) for p in portfolio.positions],
                         "policy": RISK_POLICY_VERSION}, sort_keys=True)
    identifier = hashlib.sha256(stable.encode()).hexdigest()[:24]
    return RiskDecision(identifier, status, conviction, tier, plan, portfolio.existing_risk,
                        portfolio.existing_risk + proposal, exposure,
                        daily_result.flatten_required, reasons)


def enforce_layer6_ceiling(plan: PositionRiskPlan, reviewed_volume: Decimal,
                           reviewed_stop: Decimal, side: Side) -> bool:
    """Return whether a future review only preserves or reduces Layer 5 exposure."""
    stop_not_looser = (reviewed_stop >= plan.stop if side is Side.LONG
                       else reviewed_stop <= plan.stop)
    return Decimal(0) <= reviewed_volume <= plan.volume and stop_not_looser
