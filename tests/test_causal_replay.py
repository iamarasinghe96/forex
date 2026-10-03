from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

from forex.analysis import Side
from forex.domain import Candle, Timeframe
from forex.risk import protective_stop

sys.path.insert(0, str(Path("scripts").resolve()))


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, Path(f"scripts/{name}.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


replay = load("causal_replay")
research_db = load("research_db")
START = datetime(2024, 1, 8, tzinfo=UTC)  # A Monday.


def hour(i: int, close: float, **kw: object) -> object:
    return replay.Hour(START + timedelta(hours=i), kw.get("open", close), kw.get("high", close + 0.0002),
                       kw.get("low", close - 0.0002), close, kw.get("direction", 1), kw.get("stop", close - 0.002),
                       kw.get("atr", 0.0005), kw.get("signal", False), kw.get("trend", True), kw.get("segment", 0))


def test_replay_moves_stops_with_the_live_bots_own_rule() -> None:
    hours = [hour(0, 1.1000, stop=1.0980),
             hour(1, 1.1025, high=1.1030, low=1.1020),               # Reaches +1.5R.
             hour(2, 1.1012, open=1.1025, high=1.1026, low=1.1010)]  # Falls through the trailed stop.
    expected = float(protective_stop(Side.LONG, Decimal("1.1000"), Decimal("1.0980"), Decimal("1.0980"),
                                     Decimal("1.1030"), Decimal("0.0005"), Decimal(3)).stop)
    assert expected == pytest.approx(1.1015)  # Break-even, then 3 x ATR behind the bar's best price.
    exit_index, gross, cost, still_open = replay.outcomes("EURUSD", hours, 10, 1.0, 3, 0)[0]
    assert (exit_index, still_open) == (2, False)
    assert gross == pytest.approx((expected - 1.1000) / 0.0020)
    assert cost == pytest.approx(0.00009 / 0.0020)


def test_no_trade_spans_a_data_hole() -> None:
    hours = [hour(i, 1.1 + 0.0001 * i, segment=0 if i < 4 else 1) for i in range(8)]
    result = replay.outcomes("EURUSD", hours, 10, 1.0, 3, 0)
    assert result[2][0] == 3 and result[2][3] is True  # Censored at the last bar before the hole.
    trades = replay.run(hours, result, lambda i, h: i == 2)
    assert replay.summary(trades, 1.0)["trades"] == 0 and replay.summary(trades, 1.0)["censored_or_open"] == 1


def test_matched_controls_only_enter_where_the_strategy_could() -> None:
    # Every trade is stopped on the next bar; trend regimes on even hours only.
    hours = [hour(i, 1.1, low=1.0975, stop=1.098, trend=i % 2 == 0, signal=i % 4 == 0) for i in range(400)]
    streams = {"EURUSD": hours}
    exits = {"EURUSD": replay.outcomes("EURUSD", hours, 10, 1.0, 3, 0)}
    strategy = {"EURUSD": replay.run(hours, exits["EURUSD"], lambda i, h: h.signal)}

    def cell(s: str, i: int, h: object) -> tuple[object, ...]:
        return (s,)

    rates = replay.entry_rates(streams, exits, strategy, lambda h: h.trend, cell)
    runs = replay.controls(streams, exits, 50, 7, lambda h: h.trend, cell, rates)
    assert all(hours[i].trend for trades in runs for i, *_ in trades)
    comparison = replay.compare(strategy["EURUSD"], runs, 1.0)
    assert comparison["gross"]["strategy_avg_r"] == pytest.approx(-1.0)  # type: ignore[index]


def candles(times: list[datetime]) -> list[Candle]:
    return [Candle.from_values("EURUSD", Timeframe.H1, t, "1.1", "1.1002", "1.0998", "1.1", 1, 1, 0) for t in times]


def test_segments_split_at_weekday_holes_but_not_weekends() -> None:
    week = [START + timedelta(hours=h) for h in range(24 * 5 - 2)]          # Mon 00:00 to Fri 21:00.
    after_weekend = [START + timedelta(days=6, hours=22 + h) for h in range(30)]  # Sunday 22:00 onwards.
    assert research_db.missing_trading_hours(week[-1], after_weekend[0]) == 0
    assert len(research_db.segments(candles(week + after_weekend), 48)) == 1
    holed = week[:24] + week[24 + 60:]                                          # 60 weekday hours missing.
    assert research_db.missing_trading_hours(holed[23], holed[24]) == 60
    assert [len(part) for part in research_db.segments(candles(holed), 48)] == [24, len(week) - 84]
