from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from test_learning import runtime_fixture
from test_risk import POLICY, account, spec

from forex.analysis import Side
from forex.config import load_config
from forex.domain import Timeframe
from forex.learning import strategy_version
from forex.risk import (
    OpenRiskPosition,
    RiskBlockReason,
    notional_per_lot,
    size_position,
    used_margin,
)

D = Decimal
MARGIN_POLICY = replace(POLICY, enforce_margin=True)
# EURUSD on an AUD account: 1.5 AUD per 0.00001 tick per lot, so one lot at 1.10 is A$165,000.
EURUSD = spec(tick_value=D("1.5"), stops_level_points=0)


def test_notional_and_used_margin() -> None:
    assert notional_per_lot(D("1.1"), D(".00001"), D("1.5")) == D("165000")
    held = OpenRiskPosition("EURUSD", Side.LONG, D("1.1"), D("1.09"), D("0.1"), D(".00001"), D("1.5"))
    assert used_margin((held,), 30) == D("550")  # A$16,500 notional at 30:1.


def test_five_percent_risk_is_cut_to_what_free_margin_allows() -> None:
    small = account("1000")
    # 15-pip stop: A$225 per lot at risk, so 5% (A$50) would be 0.22 lots = A$36k notional (36:1).
    loose, _ = size_position(small, EURUSD, Side.LONG, D("1.1"), D("1.0985"), D(".05"), POLICY)
    assert loose is not None and loose.volume == D("0.22")
    capped, _ = size_position(small, EURUSD, Side.LONG, D("1.1"), D("1.0985"), D(".05"), MARGIN_POLICY)
    assert capped is not None and capped.volume == D("0.18")  # A$1,000 x 30 / A$165,000 per lot.
    assert capped.actual_risk_amount == D("40.5")              # 4.05%: below the 5% budget.
    # A wide stop needs little margin, so the full 5% stands.
    wide, _ = size_position(small, EURUSD, Side.LONG, D("1.1"), D("1.0950"), D(".05"), MARGIN_POLICY)
    assert wide is not None and wide.volume == D("0.06")


@pytest.mark.parametrize("in_use", [D("1000"), D("995")])
def test_no_free_margin_blocks_the_trade(in_use: Decimal) -> None:
    plan, reasons = size_position(account("1000"), EURUSD, Side.LONG, D("1.1"), D("1.0985"), D(".05"),
                                  MARGIN_POLICY, None, in_use)
    assert plan is None and reasons == (RiskBlockReason.INSUFFICIENT_MARGIN,)


def test_margin_switch_changes_policy_identity_only_when_on() -> None:
    assert replace(POLICY, enforce_margin=False).policy_id == POLICY.policy_id
    assert MARGIN_POLICY.policy_id != POLICY.policy_id


def test_paper_h4_bars_are_built_from_h1_on_research_boundaries(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, _, feed = runtime_fixture(tmp_path, monkeypatch)
    import forex.runtime as module
    original, seen = module.analyse_market, []

    def spy(symbol, h1, h4, now, config):  # type: ignore[no-untyped-def]
        seen.append(h4)
        return original(symbol, h1, h4, now, config)

    monkeypatch.setattr("forex.runtime.analyse_market", spy)
    runtime.cycle()
    assert all(call.args[1] is Timeframe.H1 for call in feed.candles.call_args_list)  # No MT5 H4 bars.
    assert seen and seen[0] and all(bar.timestamp_utc.hour % 4 == 0 for bar in seen[0])
    assert all(bar.timeframe is Timeframe.H4 for bar in seen[0])


def test_settings_version_records_how_h4_bars_are_built() -> None:
    base = load_config(Path("config.yaml"))
    shifted = base.model_copy(update={"market_data": base.market_data.model_copy(update={"h4_alignment_hour_utc": 2})})
    assert strategy_version(shifted) != strategy_version(base)
