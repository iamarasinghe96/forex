"""Pure Layer 5 conviction, exposure, and protective-management policy.

No function in this module reads a clock, database, broker, network, or mutable global.
The constants are versioned operator policy, not empirically validated parameters.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import Enum
from typing import ClassVar

from forex.analysis import Availability, Evidence, Side, TradeCandidate
from forex.config import ScoringConfig
from forex.domain import AccountState, SymbolSpec
from forex.scoring import ScoreResult

FUSION_POLICY_VERSION = "layer5-fusion-v1-unvalidated"
RISK_POLICY_IMPLEMENTATION_VERSION = "layer5-risk-v1"


def _canonical_decimal(value: Decimal) -> str:
    """Serialize equal finite Decimal values identically without float conversion."""
    if not value.is_finite():
        raise ValueError("risk policy values must be finite")
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


@dataclass(frozen=True)
class RiskPolicy:
    """Immutable broker-neutral policy populated from operator configuration."""

    max_leverage: int
    minimum_reward_risk: Decimal
    max_concurrent_positions: int
    max_simultaneous_risk: Decimal
    daily_loss_limit: Decimal
    minimum_conviction: Decimal
    medium_conviction: Decimal
    high_conviction: Decimal
    low_risk_percent: Decimal
    medium_risk_percent: Decimal
    high_risk_percent: Decimal
    # Cap volume so the account's margin (notional / account leverage, for all open positions plus
    # the new one) fits within equity, as a real broker would. Off keeps the older paper sizing.
    enforce_margin: bool = False

    implementation_version: ClassVar[str] = RISK_POLICY_IMPLEMENTATION_VERSION

    def __post_init__(self) -> None:
        if self.max_leverage <= 0 or self.max_concurrent_positions <= 0:
            raise ValueError("leverage and position limits must be positive")
        if self.minimum_reward_risk < Decimal("1.5"):
            raise ValueError("minimum reward:risk must be at least 1.5")
        if not Decimal(0) < self.max_simultaneous_risk <= Decimal(1):
            raise ValueError("maximum simultaneous risk must be within 0..1")
        if not Decimal(0) < self.daily_loss_limit <= Decimal(1):
            raise ValueError("daily loss limit must be within 0..1")
        if not (Decimal(0) <= self.minimum_conviction < self.medium_conviction
                < self.high_conviction <= Decimal(100)):
            raise ValueError("conviction thresholds must satisfy 0 <= minimum < medium < high <= 100")
        risks = (self.low_risk_percent, self.medium_risk_percent, self.high_risk_percent)
        if any(not value.is_finite() or not Decimal(0) < value <= Decimal(1) for value in risks):
            raise ValueError("conviction risk percentages must be within 0..1")
        if not self.low_risk_percent <= self.medium_risk_percent <= self.high_risk_percent:
            raise ValueError("conviction risk percentages must be non-decreasing")

    @property
    def policy_id(self) -> str:
        """Content-addressed identity of every setting that affects risk behaviour."""
        settings: dict[str, object] = {
            "daily_loss_limit": _canonical_decimal(self.daily_loss_limit),
            "high_conviction": _canonical_decimal(self.high_conviction),
            "high_risk_percent": _canonical_decimal(self.high_risk_percent),
            "low_risk_percent": _canonical_decimal(self.low_risk_percent),
            "max_concurrent_positions": self.max_concurrent_positions,
            "max_leverage": self.max_leverage,
            "max_simultaneous_risk": _canonical_decimal(self.max_simultaneous_risk),
            "medium_conviction": _canonical_decimal(self.medium_conviction),
            "medium_risk_percent": _canonical_decimal(self.medium_risk_percent),
            "minimum_conviction": _canonical_decimal(self.minimum_conviction),
            "minimum_reward_risk": _canonical_decimal(self.minimum_reward_risk),
        }
        if self.enforce_margin:  # Only when on, so existing policy identities are unchanged.
            settings["enforce_margin"] = True
        canonical = json.dumps(settings, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return f"{self.implementation_version}-{fingerprint}"


class ConvictionBand(str, Enum):
    BELOW_THRESHOLD = "BELOW_MINIMUM"
    RISK_2_PERCENT = "LOW"
    RISK_3_5_PERCENT = "MEDIUM"
    RISK_5_PERCENT = "HIGH"


class DecisionStatus(str, Enum):
    SIGNAL_NOT_ELIGIBLE = "SIGNAL_NOT_ELIGIBLE"
    HARD_RISK_BLOCK = "HARD_RISK_BLOCK"
    HALT_FLATTEN_REQUIRED = "HALT_FLATTEN_REQUIRED"
    ELIGIBLE = "ELIGIBLE"


class RiskBlockReason(str, Enum):
    SETUP_SCORE_NOT_POSITIVE = "SETUP_EXPECTED_R_NOT_ABOVE_MINIMUM"
    CONVICTION_BELOW_MINIMUM = "CONVICTION_BELOW_CONFIGURED_MINIMUM"
    INVALID_LEVERAGE = "ACCOUNT_LEVERAGE_EXCEEDS_CONFIGURED_MAXIMUM"
    INVALID_STOP_SIDE = "STRUCTURAL_STOP_ON_WRONG_SIDE"
    STOP_TOO_CLOSE = "BROKER_MINIMUM_STOP_DISTANCE_VIOLATED"
    INVALID_SYMBOL_SPEC = "INVALID_TICK_OR_VOLUME_PROPERTIES"
    VOLUME_BELOW_MINIMUM = "BROKER_MINIMUM_VOLUME_EXCEEDS_RISK_BUDGET"
    REWARD_RISK_BELOW_1_5 = "OBJECTIVE_BELOW_CONFIGURED_MINIMUM_R"
    MAX_POSITIONS = "CONFIGURED_MAXIMUM_OPEN_POSITIONS"
    PORTFOLIO_RISK = "CONFIGURED_MAXIMUM_SIMULTANEOUS_RISK"
    CIRCUIT_BREAKER = "CONFIGURED_DAILY_LOSS_CIRCUIT_BREAKER"
    KILL_SWITCH = "KILL_SWITCH_ACTIVE"
    INSUFFICIENT_MARGIN = "INSUFFICIENT_FREE_MARGIN_AT_ACCOUNT_LEVERAGE"


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
    permitted_position_plan: PositionRiskPlan | None
    diagnostic_proposal: PositionRiskPlan | None
    existing_portfolio_risk: Decimal
    proposed_portfolio_risk: Decimal
    exposure: ExposureDiagnostics
    flatten_required: bool
    reasons: tuple[RiskBlockReason, ...]
    risk_policy_implementation_version: str
    risk_policy_id: str

    def __post_init__(self) -> None:
        if self.status is DecisionStatus.ELIGIBLE and self.permitted_position_plan is None:
            raise ValueError("ELIGIBLE decision requires a permitted position plan")
        if self.status is not DecisionStatus.ELIGIBLE and self.permitted_position_plan is not None:
            raise ValueError("blocked decision cannot expose a permitted position plan")


def risk_tier(conviction: Decimal, policy: RiskPolicy) -> RiskTier:
    if not conviction.is_finite() or conviction < 0 or conviction > 100:
        raise ValueError("conviction must be finite and within 0..100")
    if conviction < policy.minimum_conviction:
        return RiskTier(ConvictionBand.BELOW_THRESHOLD, None)
    if conviction < policy.medium_conviction:
        return RiskTier(ConvictionBand.RISK_2_PERCENT, policy.low_risk_percent)
    if conviction < policy.high_conviction:
        return RiskTier(ConvictionBand.RISK_3_5_PERCENT, policy.medium_risk_percent)
    return RiskTier(ConvictionBand.RISK_5_PERCENT, policy.high_risk_percent)


def risk_percent_for_score(expected_r: float, config: ScoringConfig) -> Decimal:
    """Fraction of balance, as in existing risk tiers: 0.01 means 1%, not 0.01%."""
    if not math.isfinite(expected_r):
        raise ValueError("predicted expected R must be finite")
    if expected_r <= config.skip_below_expected_r:
        return Decimal(0)
    kelly = Decimal(str(config.kelly_fraction)) * Decimal(str(expected_r)) / Decimal(str(config.variance_r))
    return min(Decimal(str(config.max_risk_percent)) / 100,
               max(Decimal(str(config.min_risk_percent)) / 100, kelly))


def derive_conviction(candidate: TradeCandidate, policy: RiskPolicy,
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
    tier = risk_tier(final, policy)
    reasons = (() if tier.risk_percent is not None
               else (RiskBlockReason.CONVICTION_BELOW_MINIMUM.value,))
    return ConvictionResult(
        candidate.candidate_id, candidate.evaluation_id, candidate.strategy_version,
        candidate.parameter_version, FUSION_POLICY_VERSION, technical, final,
        candidate.supporting_evidence, candidate.opposing_evidence, tuple(availability),
        tier.band, tier.risk_percent is not None, reasons,
    )


def evaluate_daily_risk(state: DailyRiskState, policy: RiskPolicy) -> DailyRiskResult:
    if state.opening_balance <= 0:
        raise ValueError("session opening balance must be positive")
    loss = max(Decimal(0), (state.opening_balance - state.current_equity)
               / state.opening_balance)
    circuit = state.circuit_breaker_triggered or loss >= policy.daily_loss_limit
    reasons: list[RiskBlockReason] = []
    if circuit:
        reasons.append(RiskBlockReason.CIRCUIT_BREAKER)
    if state.kill_switch_active:
        reasons.append(RiskBlockReason.KILL_SWITCH)
    blocked = circuit or state.kill_switch_active
    return DailyRiskResult(state.session_id, loss, circuit, state.kill_switch_active,
                           blocked, blocked, tuple(reasons))


def minimum_objective(side: Side, entry: Decimal, stop: Decimal,
                      policy: RiskPolicy) -> Decimal:
    distance = abs(entry - stop)
    return (entry + policy.minimum_reward_risk * distance if side is Side.LONG
            else entry - policy.minimum_reward_risk * distance)


def notional_per_lot(price: Decimal, tick_size: Decimal, tick_value: Decimal) -> Decimal:
    """Account-currency value of one lot: a tick is worth tick_value, so price/tick_size ticks
    is the whole position (e.g. 1.10 EURUSD with 1.5 AUD per 0.00001 tick is about A$165k)."""
    return price / tick_size * tick_value


def used_margin(positions: tuple[OpenRiskPosition, ...], leverage: int) -> Decimal:
    """Margin held by open positions at the account leverage (valued at their entry prices)."""
    if leverage <= 0:
        return Decimal(0)
    return sum((notional_per_lot(p.entry, p.tick_size, p.tick_value) * p.volume for p in positions),
               Decimal(0)) / leverage


def size_position(account: AccountState, spec: SymbolSpec, side: Side, entry: Decimal,
                  stop: Decimal, risk_percent: Decimal,
                  policy: RiskPolicy, objective: Decimal | None = None,
                  margin_in_use: Decimal = Decimal(0)) -> tuple[PositionRiskPlan | None,
                                                                tuple[RiskBlockReason, ...]]:
    if account.leverage > policy.max_leverage:
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
    min_objective = minimum_objective(side, entry, stop, policy)
    if objective is not None:
        reward = ((objective - entry) if side is Side.LONG else (entry - objective))
        if reward / distance < policy.minimum_reward_risk:
            return None, (RiskBlockReason.REWARD_RISK_BELOW_1_5,)
    loss_per_lot = distance / spec.tick_size * spec.tick_value
    budget = account.balance * risk_percent
    raw = budget / loss_per_lot
    capped = min(raw, spec.volume_max)
    margin_bound = False
    if policy.enforce_margin:
        free = account.equity - margin_in_use
        if account.leverage <= 0 or free <= 0:
            return None, (RiskBlockReason.INSUFFICIENT_MARGIN,)
        affordable = free * account.leverage / notional_per_lot(entry, spec.tick_size, spec.tick_value)
        margin_bound = affordable < capped
        capped = min(capped, affordable)
    volume = (capped / spec.volume_step).to_integral_value(rounding=ROUND_FLOOR) * spec.volume_step
    if volume < spec.volume_min:
        return None, (RiskBlockReason.INSUFFICIENT_MARGIN if margin_bound else RiskBlockReason.VOLUME_BELOW_MINIMUM,)
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
                policy: RiskPolicy,
                contexts: tuple[ContextualConviction, ...] = (), *,
                setup_score: ScoreResult | None = None,
                scoring: ScoringConfig | None = None) -> RiskDecision:
    conviction = derive_conviction(candidate, policy, contexts)
    tier = risk_tier(conviction.final_conviction, policy)
    dynamic = scoring is not None and scoring.enabled and not scoring.shadow
    if dynamic:
        if setup_score is None or scoring is None:
            raise ValueError("enabled setup sizing requires a validated model score")
        fraction = risk_percent_for_score(setup_score.expected_r, scoring)
        tier = RiskTier(conviction.band, fraction if fraction > 0 else None)
    daily_result = evaluate_daily_risk(daily, policy)
    plan: PositionRiskPlan | None = None
    reasons: tuple[RiskBlockReason, ...]
    if daily_result.new_entries_blocked:
        status, reasons = DecisionStatus.HALT_FLATTEN_REQUIRED, daily_result.reasons
    elif tier.risk_percent is None:
        status, reasons = DecisionStatus.SIGNAL_NOT_ELIGIBLE, (
            RiskBlockReason.SETUP_SCORE_NOT_POSITIVE if dynamic else RiskBlockReason.CONVICTION_BELOW_MINIMUM,)
    else:
        margin = used_margin(portfolio.positions, account.leverage) if policy.enforce_margin else Decimal(0)
        plan, reasons = size_position(account, spec, candidate.side, entry, stop,
                                      tier.risk_percent, policy, objective, margin)
        status = DecisionStatus.ELIGIBLE if plan else DecisionStatus.HARD_RISK_BLOCK
        if plan is not None and len(portfolio.positions) >= policy.max_concurrent_positions:
            status, reasons = DecisionStatus.HARD_RISK_BLOCK, (RiskBlockReason.MAX_POSITIONS,)
        if plan is not None and portfolio.existing_risk + plan.actual_risk_amount > \
                account.balance * policy.max_simultaneous_risk:
            status, reasons = DecisionStatus.HARD_RISK_BLOCK, (RiskBlockReason.PORTFOLIO_RISK,)
    proposal = plan.actual_risk_amount if plan else Decimal(0)
    exposure = exposure_diagnostics(portfolio.positions, candidate.symbol, candidate.side, proposal)
    canonical_positions = sorted(
        [{"symbol": p.symbol, "side": p.side.value, "entry": str(p.entry),
          "stop": str(p.current_stop), "volume": str(p.volume),
          "tick_size": str(p.tick_size), "tick_value": str(p.tick_value)}
         for p in portfolio.positions],
        key=lambda item: tuple(item[key] for key in sorted(item)),
    )
    stable = json.dumps({
        "candidate": candidate.candidate_id,
        "evaluation": candidate.evaluation_id,
        "account": {"balance": str(account.balance), "equity": str(account.equity),
                    "leverage": account.leverage, "currency": account.currency},
        "symbol_spec": {"broker_name": spec.broker_name, "point": str(spec.point),
                        "tick_size": str(spec.tick_size), "tick_value": str(spec.tick_value),
                        "volume_min": str(spec.volume_min), "volume_max": str(spec.volume_max),
                        "volume_step": str(spec.volume_step),
                        "stops_level_points": spec.stops_level_points},
        "entry": str(entry), "stop": str(stop), "objective": str(objective),
        "daily": {"session": daily.session_id, "opening_balance": str(daily.opening_balance),
                  "current_equity": str(daily.current_equity),
                  "circuit_breaker_triggered": daily.circuit_breaker_triggered,
                  "kill_switch_active": daily.kill_switch_active},
        "positions": canonical_positions,
        "policy": {"implementation_version": policy.implementation_version,
                   "policy_id": policy.policy_id,
                   "max_leverage": policy.max_leverage,
                   "minimum_reward_risk": str(policy.minimum_reward_risk),
                   "max_concurrent_positions": policy.max_concurrent_positions,
                   "max_simultaneous_risk": str(policy.max_simultaneous_risk),
                   "daily_loss_limit": str(policy.daily_loss_limit),
                   "thresholds": [str(policy.minimum_conviction),
                                  str(policy.medium_conviction),
                                  str(policy.high_conviction)],
                   "risk_percentages": [str(policy.low_risk_percent),
                                        str(policy.medium_risk_percent),
                                        str(policy.high_risk_percent)]},
        "contexts": [{"source": item.source, "availability": item.availability.value,
                      "conviction": str(item.conviction), "confidence": str(item.confidence)}
                     for item in contexts],
        "setup_sizing": ({"model_sha256": setup_score.model_sha256,
                          "expected_r": setup_score.expected_r,
                          "config": scoring.model_dump(mode="json")} if dynamic and setup_score and scoring else None),
    }, sort_keys=True)
    identifier = hashlib.sha256(stable.encode()).hexdigest()[:24]
    permitted = plan if status is DecisionStatus.ELIGIBLE else None
    return RiskDecision(identifier, status, conviction, tier, permitted, plan,
                        portfolio.existing_risk,
                        portfolio.existing_risk + proposal, exposure,
                        daily_result.flatten_required, reasons,
                        policy.implementation_version, policy.policy_id)


def enforce_layer6_ceiling(plan: PositionRiskPlan, reviewed_volume: Decimal,
                           reviewed_stop: Decimal, reviewed_objective: Decimal,
                           side: Side) -> bool:
    """Return whether a future review only preserves or reduces Layer 5 exposure."""
    stop_not_looser = (reviewed_stop >= plan.stop if side is Side.LONG
                       else reviewed_stop <= plan.stop)
    objective_preserved = (reviewed_objective >= plan.minimum_objective
                           if side is Side.LONG else
                           reviewed_objective <= plan.minimum_objective)
    return (Decimal(0) <= reviewed_volume <= plan.volume and stop_not_looser
            and objective_preserved)
