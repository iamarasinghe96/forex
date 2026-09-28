from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from forex.domain import Candle, Timeframe
from forex.errors import OperatorError
from forex.market_data import (
    CandleRepository,
    GapKind,
    assert_fresh,
    detect_gaps,
    validate_candle_order,
)
from forex.persistence import initialise_database


def candle(at: datetime, timeframe: Timeframe = Timeframe.H1, close: str = "1.1") -> Candle:
    return Candle(
        "EURUSD",
        timeframe,
        at,
        Decimal("1.1"),
        Decimal("1.2"),
        Decimal("1.0"),
        Decimal(close),
        100,
        12,
        0,
    )


def test_candle_requires_utc_and_valid_ohlc():
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        candle(datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="Malformed OHLC"):
        Candle(
            "EURUSD",
            Timeframe.H1,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            Decimal("1.3"),
            Decimal("1.2"),
            Decimal("1.0"),
            Decimal("1.1"),
            1,
            1,
            0,
        )


def test_candle_order_must_be_strictly_increasing():
    later = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(OperatorError, match="strictly increasing UTC order"):
        validate_candle_order([candle(later), candle(later - timedelta(hours=1))])


def test_stale_data_is_rejected_with_operator_action():
    now = datetime(2026, 1, 6, 12, tzinfo=timezone.utc)
    with pytest.raises(OperatorError, match="Check the MT5 connection"):
        assert_fresh(now - timedelta(hours=4), now, timedelta(hours=3), "EURUSD H1")


def test_weekend_gap_is_expected_but_midweek_gap_is_unexplained():
    friday = datetime(2026, 1, 2, 21, tzinfo=timezone.utc)
    sunday = datetime(2026, 1, 4, 23, tzinfo=timezone.utc)
    weekend = detect_gaps([candle(friday), candle(sunday)])
    assert weekend[0].kind is GapKind.EXPECTED_WEEKEND

    monday = datetime(2026, 1, 5, 10, tzinfo=timezone.utc)
    midweek = detect_gaps([candle(monday), candle(monday + timedelta(hours=3))])
    assert midweek[0].kind is GapKind.UNEXPLAINED
    assert midweek[0].missing_bars == 2


def test_weekend_staleness_is_not_a_feed_failure():
    friday = datetime(2026, 1, 2, 21, tzinfo=timezone.utc)
    sunday = datetime(2026, 1, 4, 21, tzinfo=timezone.utc)
    assert_fresh(friday, sunday, timedelta(hours=3), "EURUSD H1")


def test_sqlite_upsert_is_idempotent_and_updates_incomplete_bar(tmp_path):
    path = tmp_path / "candles.sqlite3"
    initialise_database(path)
    repository = CandleRepository(path)
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert repository.upsert([candle(at)]) == 1
    assert repository.upsert([candle(at, close="1.15")]) == 1
    loaded = repository.load("EURUSD", Timeframe.H1)
    assert len(loaded) == 1
    assert loaded[0].close == Decimal("1.15")
    assert loaded[0].time_utc.tzinfo is timezone.utc
