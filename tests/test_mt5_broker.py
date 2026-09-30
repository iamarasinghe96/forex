from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from forex.broker.execution_mt5 import MT5ExecutionBroker
from forex.broker.ic_markets_clock import server_timestamp_to_utc, utc_to_server_datetime
from forex.broker.mt5 import MT5Broker
from forex.config import BrokerConfig, MarketDataConfig
from forex.domain import Timeframe
from forex.errors import OperatorError
from forex.market_data import validate_tick_freshness


def ns(**values):
    return SimpleNamespace(**values)


class FakeMT5:
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2
    TIMEFRAME_H1 = 60
    TIMEFRAME_H4 = 240

    def __init__(self):
        self.selected = []
        self.symbols = {
            "EURUSD.a": ns(name="EURUSD.a", currency_base="EUR", currency_profit="USD", digits=5,
                point=0.00001, trade_tick_size=0.00001, trade_tick_value=1.0,
                trade_contract_size=100000, volume_min=0.01, volume_max=100,
                volume_step=0.01, trade_stops_level=10, trade_freeze_level=2, filling_mode=1),
            "USDAUD.a": ns(name="USDAUD.a", currency_base="USD", currency_profit="AUD", digits=5,
                point=0.00001, trade_tick_size=0.00001, trade_tick_value=1.5,
                trade_contract_size=100000, volume_min=0.01, volume_max=100,
                volume_step=0.01, trade_stops_level=10, trade_freeze_level=2, filling_mode=1),
        }

    def initialize(self, **kwargs):
        return True

    def terminal_info(self):
        return ns(connected=True, trade_allowed=True)

    def account_info(self):
        return ns(login=23008397, currency="AUD", balance=10000, equity=9990, leverage=30, margin_mode=2)

    def shutdown(self):
        pass

    def symbols_get(self):
        return list(self.symbols.values())

    def symbol_select(self, name, enabled):
        self.selected.append(name)
        return enabled

    def symbol_info(self, name):
        return self.symbols.get(name)

    def symbol_info_tick(self, name):
        return ns(bid=1.5, ask=1.5, time_msc=1_700_000_000_000)

    def last_error(self):
        return (0, "ok")


def config():
    return BrokerConfig(login=23008397, server="ICMarketsAU-Demo", account_currency="AUD",
        symbols=["EURUSD"], magic_number=1, connect_timeout_seconds=30)


def test_connect_resolves_suffix_and_computes_live_converted_pip_value():
    api = FakeMT5()
    broker = MT5Broker(config(), "secret", api)
    account = broker.connect()
    spec = broker.resolve_symbol("EURUSD")
    assert account.currency == "AUD"
    assert spec.broker_name == "EURUSD.a"
    assert spec.pip_size == Decimal("0.00010")
    assert broker.pip_value_per_lot(spec, "AUD") == Decimal("15.000000")
    assert "EURUSD.a" in api.selected and "USDAUD.a" in api.selected


def test_read_only_connect_does_not_require_algo_trading():
    api = FakeMT5()
    api.terminal_info = lambda: ns(connected=True, trade_allowed=False)
    assert MT5Broker(config(), "secret", api).connect().currency == "AUD"


def test_execution_connect_with_algo_trading_disabled_has_button_instructions():
    api = FakeMT5()
    api.terminal_info = lambda: ns(connected=True, trade_allowed=False)
    with pytest.raises(OperatorError, match="Algo Trading"):
        MT5ExecutionBroker(config(), "secret", api).connect()


def test_account_above_leverage_cap_fails_loudly():
    api = FakeMT5()
    api.account_info = lambda: ns(login=1, currency="AUD", balance=1, equity=1, leverage=100, margin_mode=2)
    with pytest.raises(OperatorError, match="above the configured ASIC cap"):
        MT5Broker(config(), "secret", api).connect()


@pytest.mark.parametrize(
    ("server_time", "expected"),
    [
        (datetime(2026, 9, 28, 11, tzinfo=UTC), datetime(2026, 9, 28, 8, tzinfo=UTC)),
        (datetime(2026, 1, 15, 11, tzinfo=UTC), datetime(2026, 1, 15, 9, tzinfo=UTC)),
    ],
)
def test_ic_markets_server_time_normalizes_with_historical_dst(server_time, expected):
    assert server_timestamp_to_utc(server_time.timestamp()) == expected


@pytest.mark.parametrize(
    ("utc_time", "server_time"),
    [
        (datetime(2026, 9, 28, 8, 14, tzinfo=UTC),
         datetime(2026, 9, 28, 11, 14, tzinfo=UTC)),
        (datetime(2026, 1, 15, 8, 14, tzinfo=UTC),
         datetime(2026, 1, 15, 10, 14, tzinfo=UTC)),
    ],
)
def test_utc_request_bound_encodes_ic_markets_server_time(utc_time, server_time):
    assert utc_to_server_datetime(utc_time) == server_time


def test_tick_normalizes_server_wall_time_to_utc():
    api = FakeMT5()
    api.symbol_info_tick = lambda _name: ns(
        bid=1.5, ask=1.6,
        time_msc=datetime(2026, 9, 28, 11, tzinfo=UTC).timestamp() * 1000,
    )

    tick = MT5Broker(config(), "secret", api).tick("EURUSD.a")

    assert tick.time_utc == datetime(2026, 9, 28, 8, tzinfo=UTC)


def test_normalized_genuinely_future_tick_still_fails_freshness():
    api = FakeMT5()
    api.symbol_info_tick = lambda _name: ns(
        bid=1.5, ask=1.6,
        time_msc=datetime(2026, 9, 28, 11, 0, 1, tzinfo=UTC).timestamp() * 1000,
    )
    tick = MT5Broker(config(), "secret", api).tick("EURUSD.a")

    with pytest.raises(OperatorError, match="future"):
        validate_tick_freshness(
            tick, datetime(2026, 9, 28, 8, tzinfo=UTC),
            MarketDataConfig(),
        )


def test_live_server_clock_sanity_accepts_expected_offset_and_rejects_mismatch():
    api = FakeMT5()
    api.symbol_info_tick = lambda _name: ns(
        bid=1.5, ask=1.6,
        time_msc=datetime(2026, 9, 28, 11, tzinfo=UTC).timestamp() * 1000,
    )
    broker = MT5Broker(config(), "secret", api)
    broker.tick("EURUSD.a")

    broker.validate_server_clock(datetime(2026, 9, 28, 8, tzinfo=UTC), 300)
    with pytest.raises(OperatorError, match=r"GMT\+2/GMT\+3"):
        broker.validate_server_clock(datetime(2026, 9, 28, 7, tzinfo=UTC), 300)


@pytest.mark.parametrize("timeframe", [Timeframe.H1, Timeframe.H4])
def test_current_candle_query_converts_bounds_and_normalizes_result(timeframe):
    api = FakeMT5()
    captured = []

    def copy_rates_range(_symbol, _timeframe, start, end):
        captured.append((start, end))
        return [{
            "time": int(datetime(2026, 9, 28, 11, tzinfo=UTC).timestamp()),
            "open": 1, "high": 2, "low": 1, "close": 2,
            "tick_volume": 1, "spread": 0, "real_volume": 0,
        }]

    api.copy_rates_range = copy_rates_range

    candles = MT5Broker(config(), "secret", api).candles(
        "EURUSD", timeframe,
        datetime(2026, 9, 28, 7, 14, tzinfo=UTC),
        datetime(2026, 9, 28, 8, 14, tzinfo=UTC),
    )

    assert captured == [(
        datetime(2026, 9, 28, 10, 14, tzinfo=UTC),
        datetime(2026, 9, 28, 11, 14, tzinfo=UTC),
    )]
    assert candles[0].timestamp_utc == datetime(2026, 9, 28, 8, tzinfo=UTC)
    assert candles[0].timestamp_utc.utcoffset() == timedelta(0)


def test_range_bounds_on_opposite_sides_of_dst_use_individual_offsets():
    api = FakeMT5()
    captured = []

    def copy_rates_range(_symbol, _timeframe, start, end):
        captured.append((start, end))
        return [{
            "time": int(datetime(2026, 3, 9, 11, tzinfo=UTC).timestamp()),
            "open": 1, "high": 2, "low": 1, "close": 2,
            "tick_volume": 1, "spread": 0, "real_volume": 0,
        }]

    api.copy_rates_range = copy_rates_range
    MT5Broker(config(), "secret", api).candles(
        "EURUSD", Timeframe.H1,
        datetime(2026, 3, 7, 8, tzinfo=UTC), datetime(2026, 3, 9, 8, tzinfo=UTC),
    )

    assert captured == [(
        datetime(2026, 3, 7, 10, tzinfo=UTC),
        datetime(2026, 3, 9, 11, tzinfo=UTC),
    )]


def test_historical_candles_use_each_dates_offset():
    api = FakeMT5()
    api.TIMEFRAME_H1 = 60
    api.copy_rates_range = lambda *_args: [
        {
            "time": int(server_time.timestamp()),
            "open": 1, "high": 2, "low": 1, "close": 2,
            "tick_volume": 1, "spread": 0, "real_volume": 0,
        }
        for server_time in (
            datetime(2026, 1, 15, 11, tzinfo=UTC),
            datetime(2026, 9, 28, 11, tzinfo=UTC),
        )
    ]

    candles = MT5Broker(config(), "secret", api).candles(
        "EURUSD", Timeframe.H1,
        datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 10, 1, tzinfo=UTC),
    )

    assert [candle.timestamp_utc for candle in candles] == [
        datetime(2026, 1, 15, 9, tzinfo=UTC),
        datetime(2026, 9, 28, 8, tzinfo=UTC),
    ]


def test_explicit_mapping_wins_over_exact_close_only_symbol():
    api = FakeMT5()
    api.symbols["EURUSD"] = ns(**{**vars(api.symbols["EURUSD.a"]), "name": "EURUSD", "trade_mode": 3})
    cfg = config()
    cfg.symbol_overrides = {"EURUSD": "EURUSD.a"}
    broker = MT5Broker(cfg, "secret", api)
    spec = broker.resolve_symbol("EURUSD")
    assert spec.requested_name == "EURUSD"
    assert spec.broker_name == "EURUSD.a"
    assert api.selected == ["EURUSD.a"]
    # Broker-position/intent identities already suffixed remain valid.
    assert broker.resolve_symbol("EURUSD.a").broker_name == "EURUSD.a"


def test_missing_explicit_mapping_never_falls_back_to_other_instrument():
    api = FakeMT5()
    cfg = config()
    cfg.symbol_overrides = {"EURUSD": "EURUSD.missing"}
    with pytest.raises(OperatorError, match="Configured broker symbol"):
        MT5Broker(cfg, "secret", api).resolve_symbol("EURUSD")
    assert api.selected == []


def test_explicit_mapping_rejects_wrong_currency_pair():
    api = FakeMT5()
    cfg = config()
    cfg.symbol_overrides = {"EURUSD": "USDAUD.a"}
    with pytest.raises(OperatorError, match="wrong currency pair"):
        MT5Broker(cfg, "secret", api).resolve_symbol("EURUSD")
    assert api.selected == []
