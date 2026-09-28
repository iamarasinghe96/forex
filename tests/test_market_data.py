from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from forex import cli
from forex.broker.mt5 import MT5Broker
from forex.config import BrokerConfig, MarketDataConfig
from forex.domain import Candle, Tick, Timeframe
from forex.errors import OperatorError
from forex.market_data import (
    detect_gaps,
    download_history,
    validate_candle_freshness,
    validate_tick_freshness,
)
from forex.persistence import CandleStore


def candle(at, timeframe=Timeframe.H1, close="1.1"):
    return Candle("EURUSD", timeframe, at, Decimal(1), Decimal(2), Decimal("0.5"),
                  Decimal(close), 10, 2, 0)


def test_candle_validation_and_utc():
    with pytest.raises(ValueError, match="UTC"):
        candle(datetime(2025, 1, 1, tzinfo=UTC).replace(tzinfo=None))
    with pytest.raises(ValueError, match="positive"):
        Candle("X", Timeframe.H1, datetime.now(UTC), Decimal(0), Decimal(1), Decimal(1),
               Decimal(1), 0, 0, 0)
    with pytest.raises(ValueError, match="high/low"):
        Candle("X", Timeframe.H1, datetime.now(UTC), Decimal(2), Decimal(1), Decimal(1),
               Decimal(1), 0, 0, 0)
    with pytest.raises(ValueError, match="non-negative"):
        Candle("X", Timeframe.H1, datetime.now(UTC), Decimal(1), Decimal(1), Decimal(1),
               Decimal(1), -1, 0, 0)
    normalized = Candle.from_values(
        "EURUSD", Timeframe.H1, datetime(2025, 1, 1, 11, tzinfo=timezone(timedelta(hours=11))),
        1, 2, 0.5, 1.5, 0, 0, 0,
    )
    assert normalized.timestamp_utc == datetime(2025, 1, 1, tzinfo=UTC)


def test_sqlite_upsert_updates_forming_candle_and_orders(tmp_path):
    store = CandleStore(tmp_path / "data.sqlite3")
    later = candle(datetime(2025, 1, 1, 2, tzinfo=UTC))
    first = candle(datetime(2025, 1, 1, 1, tzinfo=UTC))
    store.upsert([later, first, first])
    store.upsert([candle(first.timestamp_utc, close="1.2")])
    loaded = store.load("EURUSD", Timeframe.H1)
    assert [item.timestamp_utc for item in loaded] == [first.timestamp_utc, later.timestamp_utc]
    assert loaded[0].close == Decimal("1.2")


def test_weekend_and_midweek_gaps_are_distinguished():
    config = MarketDataConfig()
    friday = candle(datetime(2025, 1, 3, 21, tzinfo=UTC))
    sunday = candle(datetime(2025, 1, 5, 22, tzinfo=UTC))
    monday_late = candle(datetime(2025, 1, 6, 2, tzinfo=UTC))
    report = detect_gaps([monday_late, friday, sunday], config)
    assert report.expected_weekend_gaps == 1
    assert report.expected_weekend_missing_bars > 0
    assert report.unexplained_missing_bars == 3


def test_summer_weekend_gap_uses_dst_shifted_utc_boundary():
    config = MarketDataConfig()
    friday_close = candle(datetime(2026, 9, 25, 20, tzinfo=UTC))
    sunday_open = candle(datetime(2026, 9, 27, 21, tzinfo=UTC))

    report = detect_gaps([friday_close, sunday_open], config)

    assert report.expected_weekend_gaps == 1
    assert report.unexplained_gaps == ()


def test_tick_freshness_ignores_weekend():
    config = MarketDataConfig()
    friday = datetime(2025, 1, 3, 21, tzinfo=UTC)
    sunday = datetime(2025, 1, 5, 23, tzinfo=UTC)
    validate_tick_freshness(Tick("EURUSD", Decimal(1), Decimal(2), friday), sunday, config)


def test_tick_freshness_rejects_stale_data():
    config = MarketDataConfig()
    with pytest.raises(OperatorError, match="stale"):
        validate_tick_freshness(
            Tick("EURUSD", Decimal(1), Decimal(2), datetime(2025, 1, 6, tzinfo=UTC)),
            datetime(2025, 1, 6, 4, tzinfo=UTC), config,
        )


def test_tick_freshness_rejects_future_data():
    config = MarketDataConfig()
    with pytest.raises(OperatorError, match="future"):
        validate_tick_freshness(
            Tick("EURUSD", Decimal(1), Decimal(2),
                 datetime(2025, 1, 6, 0, 0, 1, tzinfo=UTC)),
            datetime(2025, 1, 6, tzinfo=UTC), config,
        )


def test_candle_freshness_rejects_stale_data():
    config = MarketDataConfig()
    with pytest.raises(OperatorError, match="stale"):
        validate_candle_freshness(
            candle(datetime(2025, 1, 6, tzinfo=UTC), Timeframe.H4),
            datetime(2025, 1, 6, 9, tzinfo=UTC), config,
        )


def test_market_data_verification_captures_time_after_tick(monkeypatch, tmp_path):
    tick_time = datetime(2025, 1, 6, tzinfo=UTC)

    class Clock(datetime):
        calls = 0

        @classmethod
        def now(cls, tz=None):
            cls.calls += 1
            return tick_time + timedelta(seconds=cls.calls)

    class Broker:
        def __init__(self, *_args):
            pass

        def connect(self):
            pass

        def disconnect(self):
            pass

        def resolve_symbol(self, _symbol):
            return SimpleNamespace(broker_name="EURUSD")

        def tick(self, symbol):
            assert Clock.calls == 0
            return Tick(symbol, Decimal(1), Decimal(2), tick_time)

        def validate_server_clock(self, _now, _tolerance_seconds):
            pass

        def candles(self, symbol, timeframe, _start, end):
            return [candle(end, timeframe)]

    config = SimpleNamespace(
        broker=SimpleNamespace(symbols=["EURUSD"]),
        database=SimpleNamespace(path=tmp_path / "data.sqlite3"),
        market_data=MarketDataConfig(),
    )
    report = SimpleNamespace(
        symbol="EURUSD", earliest_utc=tick_time, latest_utc=tick_time,
        candle_count=1, depth_days=0.0, approximate_years=0.0,
        gaps=SimpleNamespace(expected_weekend_gaps=0, unexplained_gaps=()),
    )
    validated = []

    def validate_tick(tick, now, market_data):
        validated.append((tick, now))
        validate_tick_freshness(tick, now, market_data)

    monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setattr(cli, "load_config", lambda _path: config)
    monkeypatch.setattr(cli, "configure_logging", lambda _config: None)
    monkeypatch.setattr(cli, "Secrets", lambda: SimpleNamespace(mt5_password="secret"))
    monkeypatch.setattr(cli, "MT5Broker", Broker)
    monkeypatch.setattr(cli, "validate_tick_freshness", validate_tick)
    monkeypatch.setattr(cli, "validate_candle_freshness", lambda *_args: None)
    monkeypatch.setattr(cli, "download_history", lambda *_args, **_kwargs: report)

    assert cli.verify_market_data(tmp_path / "config.yaml") == 0
    assert validated == [(Tick("EURUSD", Decimal(1), Decimal(2), tick_time),
                          tick_time + timedelta(seconds=1))]


class RatesApi:
    TIMEFRAME_H1 = 60
    TIMEFRAME_H4 = 240

    def __init__(self, responses):
        self.responses = list(responses)

    def symbols_get(self):
        return [SimpleNamespace(name="EURUSD.a")]

    def symbol_select(self, name, selected):
        return selected

    def symbol_info(self, name):
        return SimpleNamespace(
            currency_base="EUR", currency_profit="USD", digits=5, point=0.00001,
            trade_tick_size=0.00001, trade_tick_value=1, trade_contract_size=100000,
            volume_min=0.01, volume_max=100, volume_step=0.01, trade_stops_level=0,
            trade_freeze_level=0, filling_mode=1,
        )

    def copy_rates_range(self, symbol, timeframe, start, end):
        assert symbol == "EURUSD.a"
        return self.responses.pop(0)

    def last_error(self):
        return 1, "temporary"


def broker(api):
    config = BrokerConfig(login=1, server="demo", account_currency="AUD", symbols=["EURUSD"],
                          magic_number=1, connect_timeout_seconds=10)
    return MT5Broker(config, "secret", api)


def row(hour, close=1.5):
    # January server time is UTC+2; the adapter normalizes this back to the requested UTC hour.
    return {"time": int(datetime(2025, 1, 1, hour + 2, tzinfo=UTC).timestamp()), "open": 1.0,
            "high": 2.0, "low": 0.5, "close": close, "tick_volume": 1, "spread": 2,
            "real_volume": 0}


def test_timeframe_mapping_suffix_retry_dedup_and_ordering():
    api = RatesApi([[], None, [row(2), row(1), row(1, 1.6)]])
    subject = broker(api)
    assert subject.timeframe_constant(Timeframe.H1) == 60
    assert subject.timeframe_constant(Timeframe.H4) == 240
    result = subject.candles("EURUSD", Timeframe.H1, datetime(2025, 1, 1, tzinfo=UTC),
                             datetime(2025, 1, 2, tzinfo=UTC))
    assert [item.timestamp_utc.hour for item in result] == [1, 2]
    assert result[0].close == Decimal("1.6")


def test_candle_range_and_repeated_empty_fail_loudly():
    subject = broker(RatesApi([[], [], []]))
    with pytest.raises(OperatorError, match="no H1 candles"):
        subject.candles("EURUSD", Timeframe.H1, datetime(2025, 1, 1, tzinfo=UTC),
                        datetime(2025, 1, 2, tzinfo=UTC))
    with pytest.raises(OperatorError, match="UTC-aware"):
        subject.candles("EURUSD", Timeframe.H1,
                        datetime(2025, 1, 1, tzinfo=UTC).replace(tzinfo=None),
                        datetime(2025, 1, 2, tzinfo=UTC))


def test_malformed_mt5_candle_fails():
    with pytest.raises(OperatorError, match="malformed"):
        broker(RatesApi([[row(1, close=-1)]])).candles(
            "EURUSD", Timeframe.H4, datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
        )


def test_partial_oldest_history_is_accepted_and_persisted(tmp_path):
    api = RatesApi([[row(1), row(2)]])
    subject = broker(api)
    store = CandleStore(tmp_path / "history.sqlite3")
    report = download_history(
        subject, store, "EURUSD", Timeframe.H1,
        MarketDataConfig(history_chunk_days=7, history_retry_count=1),
        datetime(2025, 1, 7, tzinfo=UTC),
    )
    assert report.candle_count == 2
    assert [item.timestamp_utc.hour for item in store.load("EURUSD", Timeframe.H1)] == [1, 2]
