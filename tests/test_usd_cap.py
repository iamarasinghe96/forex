from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from test_risk import POLICY, account, candidate, spec

from forex.analysis import Side
from forex.config import load_config
from forex.risk import (
    DailyRiskState,
    DecisionStatus,
    OpenRiskPosition,
    PortfolioRiskState,
    RiskBlockReason,
    decide_risk,
    usd_direction_risk,
)
from forex.risk_policy import policy_from_config

D = Decimal
DAY = DailyRiskState("d", D(10000), D(10000))


def held(symbol: str, side: Side, stop: str) -> OpenRiskPosition:
    """An open trade; with this stop its remaining risk is A$500 (5% of A$10,000), or 0 at break-even."""
    entry = D("1.30")
    return OpenRiskPosition(symbol, side, entry, D(stop), D("0.5"), D(".00001"), D("1"))


def decide(positions: tuple[OpenRiskPosition, ...], cap: str | None) -> object:
    # The candidate buys EURUSD: a bet on a weaker US dollar.
    policy = replace(POLICY, max_usd_direction_risk=None if cap is None else D(cap))
    return decide_risk(candidate(), account(), spec(), D("1.10"), D("1.09"), None,
                       PortfolioRiskState(positions), DAY, policy)


def test_same_direction_dollar_risk_is_capped_when_switched_on() -> None:
    gbp_buy = held("GBPUSD", Side.LONG, "1.29")       # Also a bet on a weaker dollar: A$500 at risk.
    blocked = decide((gbp_buy,), "0.06")
    assert blocked.status is DecisionStatus.HARD_RISK_BLOCK  # type: ignore[attr-defined]
    assert blocked.reasons == (RiskBlockReason.USD_CONCENTRATION,)  # type: ignore[attr-defined]
    assert blocked.exposure.correlation_veto_applied  # type: ignore[attr-defined]
    assert decide((gbp_buy,), "0.20").status is DecisionStatus.ELIGIBLE  # type: ignore[attr-defined]
    assert decide((gbp_buy,), None).status is DecisionStatus.ELIGIBLE  # type: ignore[attr-defined]


def test_opposite_bets_and_break_even_trades_do_not_count() -> None:
    gbp_sell = held("GBPUSD", Side.SHORT, "1.31")     # A bet on a stronger dollar: the other side.
    at_entry = held("USDJPY", Side.SHORT, "1.30")     # Weaker-dollar bet, but its stop is at entry.
    assert usd_direction_risk((gbp_sell, at_entry), "EURUSD", Side.LONG) == 0
    assert decide((gbp_sell, at_entry), "0.06").status is DecisionStatus.ELIGIBLE  # type: ignore[attr-defined]
    assert usd_direction_risk((gbp_sell,), "EURUSD", Side.SHORT) == D(500)
    assert usd_direction_risk((gbp_sell,), "EURGBP", Side.SHORT) == 0  # No US dollar in the pair.


def test_cap_is_10_percent_live_and_changes_policy_identity_only_when_set() -> None:
    config = load_config(Path("config.yaml"))
    assert config.risk.max_usd_direction_risk_percent == 10  # Operator decision, 13 Oct 2026.
    assert policy_from_config(config.risk).max_usd_direction_risk == D("0.1")
    base = policy_from_config(config.risk.model_copy(update={"max_usd_direction_risk_percent": None}))
    assert base.max_usd_direction_risk is None
    assert policy_from_config(config.risk).policy_id != base.policy_id
    assert base.policy_id == replace(base, max_usd_direction_risk=None).policy_id  # Off: identity unchanged.
    with pytest.raises(ValueError):
        replace(POLICY, max_usd_direction_risk=D("1.5"))
