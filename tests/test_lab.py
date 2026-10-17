from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_day_levels import THU, TUE, WED, random_walk

from forex.analysis import Side
from forex.domain import Candle, Timeframe
from forex.lab import __main__ as lab
from forex.lab import strategies
from forex.lab.data import History, build_series
from forex.lab.engine import Trade, portfolio, run_strategy, simulate
from forex.lab.settings import LabSettings, Rules, StrategyEntry
from forex.lab.strategies import Context, Signal, find_breakout, find_magnet, find_sweep, find_trend
from forex.persistence import CandleStore
from forex.risk import protective_stop

START = datetime(2026, 1, 12, tzinfo=UTC)


def series_of(rows: list[tuple[float, float, float, float]], gap_after: int | None = None):  # type: ignore[no-untyped-def]
    """Hourly bars (open, high, low, close) from Monday 12 Jan 2026; optionally a 5-day hole."""
    bars, at = [], START
    for k, (o, h, low, c) in enumerate(rows):
        bars.append(Candle.from_values("EURUSD", Timeframe.H1, at, o, h, low, c, 0, 0, 0))
        at += timedelta(hours=1) + (timedelta(days=5) if k == gap_after else timedelta())
    return build_series("EURUSD", bars)


FLAT = (1.1000, 1.1005, 1.0995, 1.1000)  # 14+ quiet bars give an ATR of 0.0010.
RULES = Rules(breakeven_at_r=1.0, trail_atr=3.0, target_r=2.0)


def test_exits_follow_the_paper_rules() -> None:
    # Buy at 1.1000, stop 1.0980 (risk 20 pips), target 2R = 1.1040.
    s = series_of([FLAT] * 15 + [(1.1000, 1.1045, 1.0999, 1.1040)])
    trade = simulate(s, Signal(14, 1, 1.0980), RULES, 0.0)
    assert trade and trade.reason == "TARGET" and trade.gross_r == pytest.approx(2.0)
    # Stop and target in one bar: the stop is assumed.
    s = series_of([FLAT] * 15 + [(1.1000, 1.1045, 1.0975, 1.1000)])
    assert simulate(s, Signal(14, 1, 1.0980), RULES, 0.0).reason == "STOP"  # type: ignore[union-attr]
    # A bar opening beyond the stop fills at that open, worse than the stop.
    s = series_of([FLAT] * 15 + [(1.0970, 1.0975, 1.0960, 1.0965)])
    trade = simulate(s, Signal(14, 1, 1.0980), RULES, 0.0)
    assert trade and trade.exit_price == 1.0970 and trade.gross_r == pytest.approx(-1.5)
    # Costs: 1 pip on a 20-pip stop is 0.05 R.
    costed = simulate(s, Signal(14, 1, 1.0980), RULES, 1.0)
    assert costed and costed.cost_r == pytest.approx(0.05) and costed.net() == pytest.approx(-1.55)


def test_breakeven_and_trail_match_the_live_stop_rule() -> None:
    # +1.5R bar (high 1.1030), then a fall: the stop has moved to break-even, so the trade closes at 0 R.
    s = series_of([FLAT] * 15 + [(1.1000, 1.1030, 1.0999, 1.1025), (1.1025, 1.1026, 1.0990, 1.0992)])
    trade = simulate(s, Signal(14, 1, 1.0980), Rules(breakeven_at_r=1.0, trail_atr=None, target_r=10), 0.0)
    assert trade and trade.reason == "BREAKEVEN" and trade.gross_r == pytest.approx(0.0)
    assert trade.breakeven_time == s.times[15] + timedelta(hours=1)
    # With a 1 x ATR trail the stop follows the best price; same rule as forex.risk.protective_stop.
    rules = Rules(breakeven_at_r=1.0, trail_atr=1.0, target_r=10)
    trade = simulate(s, Signal(14, 1, 1.0980), rules, 0.0)
    live = protective_stop(Side.LONG, Decimal("1.1000"), Decimal("1.0980"), Decimal("1.0980"), Decimal("1.1030"),
                           Decimal(str(s.atr[15])), Decimal("1.0"))
    assert trade and trade.reason == "TRAIL" and trade.exit_price == pytest.approx(float(live.stop))


def test_flip_time_limit_and_data_holes() -> None:
    s = series_of([FLAT] * 15 + [(1.1000, 1.1010, 1.0990, 1.1004)] * 6)
    flipped = simulate(s, Signal(14, 1, 1.0980, 1.1030), Rules(max_hours=3), 0.0, flip=True)
    assert flipped and flipped.side == -1 and flipped.stop == pytest.approx(1.1020) and flipped.target == pytest.approx(1.0970)
    assert flipped.reason == "TIME" and flipped.exit_time == s.times[17] + timedelta(hours=1)
    holed = series_of([FLAT] * 16, gap_after=15)
    trade = simulate(holed, Signal(14, 1, 1.0980), RULES, 0.0)
    assert trade and trade.censored and trade.reason == "CENSORED"
    assert simulate(s, Signal(14, 1, 1.1010), RULES, 0.0) is None  # A stop above a buy is no trade.


def trade(symbol: str, side: int, start: int, end: int, breakeven: int | None = None) -> Trade:
    t = START + timedelta(hours=start)
    return Trade(symbol, side, "", t, 1.0, 0.99, None, 0.01, START + timedelta(hours=end), 1.0, "STOP", -1.0, 0.0,
                 START + timedelta(hours=breakeven) if breakeven is not None else None, False)


def test_portfolio_rules_one_per_pair_and_us_dollar_cap() -> None:
    rules = Rules(risk_percent=5, usd_cap_percent=10)
    # Selling EURUSD and GBPUSD and buying USDJPY are all bets on a stronger dollar.
    accepted, skipped = portfolio([trade("EURUSD", -1, 0, 10), trade("EURUSD", -1, 2, 5), trade("GBPUSD", -1, 3, 10),
                                   trade("USDJPY", 1, 4, 10)], rules)
    assert [t.symbol for t in accepted] == ["EURUSD", "GBPUSD"]
    assert skipped == {"already in a trade on this pair": 1, "US-dollar cap": 1}
    # A trade at break-even no longer counts towards the cap; the opposite dollar direction never did.
    accepted, _ = portfolio([trade("EURUSD", -1, 0, 10, breakeven=2), trade("GBPUSD", -1, 3, 10),
                             trade("USDJPY", 1, 4, 10), trade("USDJPY", -1, 11, 12)], rules)
    assert [t.symbol for t in accepted] == ["EURUSD", "GBPUSD", "USDJPY", "USDJPY"]


def test_previous_day_strategies_find_their_signals() -> None:
    s = build_series("EURUSD", TUE + WED + THU)
    [sweep] = find_sweep(s, strategies.STRATEGIES["pd-sweep"].defaults)
    wed_11 = s.index[WED[11].timestamp_utc]
    assert (sweep.index, sweep.side, sweep.target) == (wed_11, -1, None)
    assert sweep.stop == pytest.approx(1.1110 + 0.1 * s.atr[wed_11])  # type: ignore[operator]
    breakout = find_breakout(s, strategies.STRATEGIES["pd-breakout"].defaults)
    assert [(b.index, b.side) for b in breakout] == [(s.index[THU[0].timestamp_utc], 1)]
    magnet = find_magnet(s, strategies.STRATEGIES["pd-magnet"].defaults)
    london = [m for m in magnet if m.index == s.index[WED[9].timestamp_utc]]
    assert len(london) == 1 and (london[0].side, london[0].target) == (1, 1.11)
    assert london[0].stop == pytest.approx(1.104)


def test_trend_v1_replays_once_then_uses_the_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forex.config import load_config
    s = build_series("EURUSD", random_walk(45, 4))
    ctx = Context(load_config(Path("config.yaml")).analysis.model_dump_json(), tmp_path, 1,
                  s.times[0] + timedelta(days=20))
    first = find_trend({"EURUSD": s}, {}, ctx)["EURUSD"]
    assert first and all(s.times[sig.index] + timedelta(hours=1) > ctx.start for sig in first)
    monkeypatch.setattr(strategies, "trend_job", lambda job: pytest.fail("the cache was not used"))
    assert find_trend({"EURUSD": s}, {}, ctx)["EURUSD"] == first


def test_unknown_strategy_setting_is_refused() -> None:
    history = History({"EURUSD": build_series("EURUSD", random_walk(30, 1))}, [], False)
    settings = LabSettings(strategies={"pd-magnet": StrategyEntry.model_validate({"min_atrs": 1})})
    with pytest.raises(SystemExit, match="unknown setting"):
        run_strategy("pd-magnet", history, settings, Context(), progress=lambda _: None)


def test_full_run_saves_reports_and_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    shutil.copy("config.yaml", tmp_path / "config.yaml")
    (tmp_path / "data").mkdir()
    CandleStore(tmp_path / "data" / "dukascopy-research.sqlite3").upsert(random_walk(120, 9))
    (tmp_path / "strategy-lab.yaml").write_text(
        "data: {start: 2019-02-01, split_year: 2019, pairs: [EURUSD]}\nrandom_runs: 20\nmin_trades: 10\n"
        "strategies: {trend-v1: {enabled: false}}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert lab.run([]) == 0
    folders = [p for p in (tmp_path / "reports" / "strategy-lab").iterdir() if p.is_dir()]
    assert len(folders) == 1 and folders[0].name.endswith("_all")
    names = {p.name for p in folders[0].iterdir()}
    assert {"summary.txt", "settings-used.yaml", "pd-sweep-trades.csv", "pd-magnet-trades.csv"} <= names
    summary = (folders[0] / "summary.txt").read_text(encoding="utf-8")
    assert "VERDICT" in summary and "beats random directions" in summary and "trend-v1" not in summary
    ledger = (tmp_path / "reports" / "strategy-lab" / "ledger.csv").read_text(encoding="utf-8").splitlines()
    assert len(ledger) == 4 and ledger[0].startswith("run,strategy")
    assert (tmp_path / "reports" / "strategy-lab" / "latest.txt").read_text(encoding="utf-8") == summary
    assert lab.study() == 0 and "PREVIOUS DAY'S HIGH AND LOW" in capsys.readouterr().out
    assert any(p.name.endswith("previous-day-study.txt") for p in (tmp_path / "reports" / "strategy-lab").iterdir())
