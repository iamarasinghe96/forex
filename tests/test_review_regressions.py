"""Offline regressions for broker-symbol trailing and learning excursion facts."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_learning import runtime_fixture
from test_risk import NOW, spec

from forex.domain import Candle, Tick, Timeframe
from forex.learning import TradeFacts, price_path


@pytest.mark.parametrize("broker_name", ["EURUSD", "EURUSD.a"])
def test_runtime_atr_reaches_position_and_trails_beyond_breakeven(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, broker_name: str,
) -> None:
    runtime, paper, feed = runtime_fixture(tmp_path, monkeypatch)
    feed.resolve_symbol.return_value = replace(spec(), broker_name=broker_name)
    feed.tick.return_value = Tick(broker_name, Decimal("1.0999"), Decimal("1.1"), NOW)
    runtime.config.paper.atr_trailing_multiple = 2.0
    runtime.cycle()  # Analysis uses EURUSD; execution resolves the broker's position name.
    position = paper.positions()[0]
    assert position.symbol == broker_name
    assert position.entry == Decimal("1.1")
    assert position.stop == Decimal("1.09")

    feed.tick.return_value = Tick(broker_name, Decimal("1.105"), Decimal("1.1051"), NOW)
    runtime.cycle()
    assert paper.positions()[0].stop == position.stop  # Trailing cannot start below +1R.

    feed.tick.return_value = Tick(broker_name, Decimal("1.111"), Decimal("1.1111"), NOW)
    runtime.cycle()
    tightened = paper.positions()[0].stop
    assert tightened > position.entry  # A missing ATR only moves the stop to breakeven.
    assert tightened == Decimal("1.111") - 2 * runtime.trailing_atr[broker_name]

    feed.tick.return_value = Tick(broker_name, Decimal("1.110"), Decimal("1.1101"), NOW)
    runtime.cycle()
    assert paper.positions()[0].stop == tightened  # A retracement cannot loosen the stop.
    feed.place_order.assert_not_called()
    feed.modify_position.assert_not_called()
    feed.close_position.assert_not_called()


def path_facts(side: str) -> TradeFacts:
    return TradeFacts(
        trade_id="path-fixture", symbol="EURUSD", side=side, setup="fixture",
        regime="fixture", style="DAY", sessions=(), volatility="UNKNOWN", conviction=None,
        entry=100, initial_stop=90 if side == "LONG" else 110, exit=100,
        exit_reason="FLATTEN", r=0, pnl_aud=0,
        opened_at_utc=NOW.isoformat(), closed_at_utc=(NOW + timedelta(hours=2)).isoformat(),
    )


def path_bars() -> list[Candle]:
    return [
        Candle.from_values("EURUSD", Timeframe.H1, NOW + timedelta(hours=index),
                           100, high, low, 100, 1, 0, 0)
        for index, (high, low) in enumerate([(102, 95), (108, 80)])
    ]


@pytest.mark.parametrize("side,best,worst", [("LONG", 0.8, -2.0), ("SHORT", 2.0, -0.8)])
def test_price_path_uses_full_multibar_extrema(side: str, best: float, worst: float) -> None:
    assert price_path(path_facts(side), path_bars()) == {
        "bars_held": 2, "best_excursion_r": best, "worst_excursion_r": worst,
    }


def test_price_path_empty_history_has_no_excursion_facts() -> None:
    assert price_path(path_facts("SHORT"), []) == {}


def test_price_path_zero_initial_risk_has_no_excursion_facts() -> None:
    assert price_path(replace(path_facts("SHORT"), initial_stop=100), path_bars()) == {}
