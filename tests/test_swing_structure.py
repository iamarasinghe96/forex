from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("scripts").resolve()))
spec = importlib.util.spec_from_file_location("swing_structure", Path("scripts/swing_structure.py"))
assert spec is not None and spec.loader is not None
swing = importlib.util.module_from_spec(spec)
sys.modules["swing_structure"] = swing
spec.loader.exec_module(swing)

START = datetime(2020, 1, 6, tzinfo=UTC)
# Thousandths of a pip-scale move above 1.1000: zigzag uptrend (higher highs and lows), a slow
# tight drift (the "rectangle"), a breakout close, a rally with a higher swing low, then a drop.
PATH = ([0, 2, 4, 3, 2, 3, 5, 7, 6, 5, 6, 8, 10, 9, 8]
        + [8.5 + 0.1 * k for k in range(10)]
        + [10.5, 11.5, 12.5, 11.8, 11.0, 11.6, 12.4, 10.0, 9.0])
BREAKOUT = 25


def bars() -> list:
    closes = [1.1 + v / 1000 for v in PATH]
    out, previous = [], closes[0]
    for i, close in enumerate(closes):
        out.append(swing.Bar(START + timedelta(hours=4 * i), previous, close + 0.0002, close - 0.0002, close))
        previous = close
    return out


def test_pivots_are_known_only_two_bars_later() -> None:
    highs, lows = swing.confirmed_pivots(bars())
    assert highs[4] == pytest.approx(1.1042) and highs[2] is None  # Swing high at bar 2.
    assert lows[6] == pytest.approx(1.1018)                        # Swing low at bar 4.


def test_chart_rules_enter_on_breakout_and_exit_below_the_new_swing_low() -> None:
    series = bars()
    states = swing.states(series)
    assert states[BREAKOUT].trend == 1 and states[BREAKOUT].tight and states[BREAKOUT].signal == 1
    assert all(s is None or s.signal == 0 for s in states[:BREAKOUT])
    exits = swing.outcomes("EURUSD", series, states, 1.0)
    trades = swing.run(len(series), exits, lambda i: states[i] is not None and states[i].signal != 0)
    assert trades[0][0] == BREAKOUT
    exit_index, r, still_open = exits[BREAKOUT]
    # Entry 1.1105, stop at the rectangle low 1.1083 (risk 22 pips), trailed to the swing low
    # 1.1108 confirmed two bars after it formed; the drop exits there, minus 0.9 pips of cost.
    assert (exit_index, still_open) == (BREAKOUT + 7, False)
    assert r == pytest.approx((1.1108 - 1.1105 - 0.00009) / 0.0022)


def test_controls_and_verdict_run() -> None:
    series = {"EURUSD": bars()}
    result = swing.evaluate(series, START, START + timedelta(days=30), 20, 1.0)
    assert result["strategy"]["trades"] == 1 and result["controls"]["n"] == 20
    assert "FAIL for this period" in swing.verdict(result)  # Far fewer than 100 trades.
