from __future__ import annotations

import random
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from forex.config import load_config
from forex.day_levels import NEW_YORK, levels_now, levels_report, levels_text, measure, trading_date
from forex.domain import Candle, Timeframe
from forex.journal import JournalStore
from forex.learning import LearningStore, overlay_path
from forex.persistence import CandleStore
from forex.telegram_commands import CommandHandler


def day_bars(day: date, base: float, spikes: dict[int, tuple[float, float, float]] | None = None,
             hours: int = 24) -> list[Candle]:
    """One forex day of hourly bars from 17:00 New York; bar i may be a (high, low, close) spike."""
    start = datetime.combine(day - timedelta(days=1), time(17), NEW_YORK).astimezone(UTC)
    bars = []
    for i in range(hours):
        high, low, close = (spikes or {}).get(i, (base + 0.0005, base - 0.0005, base))
        bars.append(Candle.from_values("EURUSD", Timeframe.H1, start + timedelta(hours=i), base, high, low, close, 0, 0, 0))
    return bars


# Jan 2026 (no daylight saving): bar 0 is 22:00 UTC, the London open is bar 10, New York's bar 15.
TUE = day_bars(date(2026, 1, 13), 1.1050, {2: (1.1100, 1.1045, 1.1050), 3: (1.1055, 1.1000, 1.1050)})
WED = day_bars(date(2026, 1, 14), 1.1070, {11: (1.1110, 1.1065, 1.1095)})  # Runs Tuesday's high, closes back.
THU = day_bars(date(2026, 1, 15), 1.1120, {12: (1.1125, 1.1100, 1.1120)})  # Opens above it all day.
SCENARIO = TUE + WED + THU


def test_forex_day_starts_at_five_pm_new_york() -> None:
    assert trading_date(datetime(2026, 1, 12, 21, 59, tzinfo=UTC)) == date(2026, 1, 12)    # 16:59 New York.
    assert trading_date(datetime(2026, 1, 12, 22, 0, tzinfo=UTC)) == date(2026, 1, 13)     # 17:00 (winter).
    assert trading_date(datetime(2026, 7, 13, 21, 0, tzinfo=UTC)) == date(2026, 7, 14)     # 17:00 (summer).
    assert trading_date(datetime(2026, 1, 11, 22, 0, tzinfo=UTC)) == date(2026, 1, 12)     # Sunday evening = Monday.


def test_study_counts_a_known_scenario() -> None:
    c = measure(SCENARIO)
    assert c["days"] == 2 and c["single"] == 2 and c["other_weekday"] == 2
    # Wednesday's London open is inside Tuesday's range and nearer the high, which is run in the next 4 hours.
    assert c["London:inside"] == 1 and c["London:inside_ran"] == 1 and c["London:single_ran"] == 1
    assert c["London:decided"] == 1 and c["London:nearer_first"] == 1 and not c.get("London:mirror_decided")
    assert c["London:magnet_real"] == 1 and not c.get("London:magnet_mirror")
    # New York opens inside too but runs nothing in its window.
    assert c["New York:inside"] == 1 and not c.get("New York:inside_ran") and not c.get("New York:single_ran")
    # Thursday opens above Wednesday's high: back to it within London's window, not within New York's.
    assert c["London:outside"] == 1 and c["London:outside_back_window"] == 1
    assert c["New York:outside"] == 1 and not c.get("New York:outside_back_day")
    # Wednesday's sweep (closed back inside) and Thursday's run (closed beyond) both moved 1 ATR back first.
    assert c["reaction_swept_back"] == 1 and c["reaction_beyond_back"] == 1


def random_walk(days: int, seed: int) -> list[Candle]:
    rng, price, day = random.Random(seed), 1.1, date(2019, 1, 7)
    bars: list[Candle] = []
    while len(bars) < days * 24:
        if day.weekday() < 5:
            start = datetime.combine(day - timedelta(days=1), time(17), NEW_YORK).astimezone(UTC)
            for i in range(24):
                close = price + rng.gauss(0, 0.001)
                high = max(price, close) + abs(rng.gauss(0, 0.0005))
                low = min(price, close) - abs(rng.gauss(0, 0.0005))
                bars.append(Candle.from_values("EURUSD", Timeframe.H1, start + timedelta(hours=i), round(price, 5),
                                               round(high, 5), round(low, 5), round(close, 5), 0, 0, 0))
                price = close
        day += timedelta(days=1)
    return bars


def test_random_prices_show_no_edge() -> None:
    """The checks must find nothing in prices with no pattern, or they would invent edges."""
    c = measure(random_walk(1500, 7))
    for session in ("London", "New York"):
        p = session + ":"
        assert abs(c[p + "magnet_real"] - c[p + "magnet_mirror"]) / c[p + "magnet_n"] < 0.03
        assert abs(c[p + "nearer_first"] / c[p + "decided"]
                   - c[p + "mirror_nearer_first"] / c[p + "mirror_decided"]) < 0.05
    for group in ("swept", "beyond"):
        back, further = c[f"reaction_{group}_back"], c[f"reaction_{group}_further"]
        assert 0.44 < back / (back + further) < 0.56
    # Chance alone gives roughly the video's 11% / 77% / 12% split of day types.
    assert 0.06 < c["inside"] / c["days"] < 0.16 and 0.70 < c["single"] / c["days"] < 0.86


def test_report_text() -> None:
    summary, full = levels_report({"EURUSD": random_walk(60, 1), "GBPUSD": []})
    assert summary.startswith("PREVIOUS DAY'S HIGH AND LOW: EURUSD, hourly prices")
    assert "magnet test" in summary and "== EURUSD ==" in full and "How to read this" in full
    assert levels_report({"EURUSD": []})[0].startswith("Not enough stored hourly prices")


def test_live_readings_for_the_scorecard() -> None:
    friday = day_bars(date(2026, 1, 16), 1.1120, {11: (1.1130, 1.1115, 1.1120)}, hours=16)
    levels = levels_now(SCENARIO + friday, datetime(2026, 1, 16, 14, tzinfo=UTC), 0.0010)
    assert levels is not None
    assert levels["date"] == "2026-01-15" and levels["type"] == "single"
    assert (levels["high"], levels["low"], levels["to_high_atr"], levels["to_low_atr"]) == (1.1125, 1.11, 0.5, 2.0)
    assert levels["today"] == {"ran_high": True, "ran_low": False, "opens": {"London": "inside", "New York": "inside"}}
    assert levels_text(levels) == (
        "Previous day (single break): high 1.1125, 0.5 ATR above price; low 1.11, 2.0 ATR below price. "
        "Today so far: ran the high; London opened inside the range; New York opened inside the range.")
    # Before the new day's first bar closes there is no "today" yet.
    later = levels_now(SCENARIO, datetime(2026, 1, 15, 22, 30, tzinfo=UTC), 0.0010)
    assert later is not None and later["today"] is None


def test_levels_command_reads_stored_prices(tmp_path: Path) -> None:
    journal = JournalStore(tmp_path / "paper.sqlite3")
    CandleStore(journal.path).upsert(random_walk(40, 3))
    handler = CommandHandler(load_config(Path("config.yaml")), LearningStore(journal.path),
                             overlay_path(journal.path), lambda: datetime(2026, 10, 17, tzinfo=UTC), journal)
    [reply] = handler.handle("/levels")
    assert reply.text.startswith("PREVIOUS DAY'S HIGH AND LOW: EURUSD") and "each pair separately" in reply.text
    assert reply.document is not None and reply.document[0] == "previous-day-levels-2026-10-17.txt"
    assert "/levels" in handler.handle("/help")[0].text
