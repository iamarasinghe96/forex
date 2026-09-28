"""Boundary adapter from validated application configuration to pure Layer 5 policy."""

from __future__ import annotations

from decimal import Decimal

from forex.config import RiskConfig
from forex.risk import RiskPolicy


def policy_from_config(config: RiskConfig) -> RiskPolicy:
    """Convert configured percentages without introducing binary-float arithmetic."""
    thresholds = config.conviction_thresholds
    risks = config.conviction_risk_percent
    return RiskPolicy(
        max_leverage=config.max_leverage,
        minimum_reward_risk=Decimal(str(config.minimum_reward_risk)),
        max_concurrent_positions=config.max_concurrent_positions,
        max_simultaneous_risk=Decimal(str(config.max_simultaneous_risk_percent)) / 100,
        daily_loss_limit=Decimal(str(config.daily_loss_percent)) / 100,
        minimum_conviction=Decimal(str(thresholds["minimum"])),
        medium_conviction=Decimal(str(thresholds["medium"])),
        high_conviction=Decimal(str(thresholds["high"])),
        low_risk_percent=Decimal(str(risks["low"])) / 100,
        medium_risk_percent=Decimal(str(risks["medium"])) / 100,
        high_risk_percent=Decimal(str(risks["high"])) / 100,
    )
