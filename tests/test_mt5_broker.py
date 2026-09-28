from decimal import Decimal
from types import SimpleNamespace

import pytest

from forex.broker.mt5 import MT5Broker
from forex.config import BrokerConfig
from forex.errors import OperatorError


def ns(**values):
    return SimpleNamespace(**values)


class FakeMT5:
    ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2

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


def test_autotrading_disabled_has_button_instructions():
    api = FakeMT5()
    api.terminal_info = lambda: ns(connected=True, trade_allowed=False)
    with pytest.raises(OperatorError, match="Algo Trading"):
        MT5Broker(config(), "secret", api).connect()


def test_account_above_leverage_cap_fails_loudly():
    api = FakeMT5()
    api.account_info = lambda: ns(login=1, currency="AUD", balance=1, equity=1, leverage=100, margin_mode=2)
    with pytest.raises(OperatorError, match="above the configured ASIC cap"):
        MT5Broker(config(), "secret", api).connect()
