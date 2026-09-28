from datetime import datetime, timedelta, timezone

import pytest

from forex.broker.mt5 import MT5Broker
from forex.config import BrokerConfig
from forex.domain import Timeframe
from forex.errors import OperatorError
from tests.test_mt5_broker import FakeMT5


def broker_config() -> BrokerConfig:
    return BrokerConfig(
        login=23008397,
        server="ICMarketsAU-Demo",
        account_currency="AUD",
        symbols=["EURUSD"],
        magic_number=1,
        connect_timeout_seconds=30,
    )


def rate(hour: int) -> dict[str, float | int]:
    return {
        "time": int(datetime(2026, 1, 1, hour, tzinfo=timezone.utc).timestamp()),
        "open": 1.10,
        "high": 1.12,
        "low": 1.09,
        "close": 1.11,
        "tick_volume": 100,
        "spread": 10,
        "real_volume": 0,
    }


class CandleMT5(FakeMT5):
    TIMEFRAME_H1 = 16385
    TIMEFRAME_H4 = 16388

    def __init__(self):
        super().__init__()
        self.range_responses: list[object] = [[rate(1), rate(0)]]
        self.position_responses: list[object] = [[rate(1), rate(0)]]

    def copy_rates_range(self, symbol, timeframe, start, end):
        return self.range_responses.pop(0)

    def copy_rates_from_pos(self, symbol, timeframe, position, count):
        return self.position_responses.pop(0)


def test_timeframe_mapping_and_normalized_utc_order():
    api = CandleMT5()
    broker = MT5Broker(broker_config(), "secret", api)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = broker.candles("EURUSD", Timeframe.H1, start, start + timedelta(days=1))
    assert broker._mt5_timeframe(Timeframe.H1) == api.TIMEFRAME_H1
    assert broker._mt5_timeframe(Timeframe.H4) == api.TIMEFRAME_H4
    assert [item.time_utc.hour for item in result] == [0, 1]
    assert all(item.time_utc.tzinfo is timezone.utc for item in result)
    assert "EURUSD.a" in api.selected


def test_empty_range_retries_then_fails_loudly(monkeypatch):
    api = CandleMT5()
    api.range_responses = [None, [], None]
    monkeypatch.setattr("forex.broker.mt5.time.sleep", lambda _: None)
    broker = MT5Broker(broker_config(), "secret", api)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(OperatorError, match="after 3 attempts"):
        broker.candles("EURUSD", Timeframe.H1, start, start + timedelta(days=1))


def test_partial_history_response_is_valid_earliest_chunk():
    api = CandleMT5()
    api.position_responses = [[rate(1), rate(0)]]
    broker = MT5Broker(broker_config(), "secret", api)
    result = broker.all_candles("EURUSD", Timeframe.H1, 100, 2, 0)
    assert len(result) == 2
    assert result[0].time_utc < result[1].time_utc


def test_empty_initial_history_fails_loudly(monkeypatch):
    api = CandleMT5()
    api.position_responses = [None, []]
    monkeypatch.setattr("forex.broker.mt5.time.sleep", lambda _: None)
    broker = MT5Broker(broker_config(), "secret", api)
    with pytest.raises(OperatorError, match="returned no bars"):
        broker.all_candles("EURUSD", Timeframe.H1, 100, 2, 0)
