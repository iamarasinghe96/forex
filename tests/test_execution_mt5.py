from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_risk import NOW

from forex.analysis import Side
from forex.broker.execution_mt5 import MT5ExecutionBroker, filling_modes
from forex.config import load_config
from forex.domain import Tick
from forex.errors import OperatorError
from forex.execution import OrderIntent


def adapter() -> tuple[MT5ExecutionBroker, Any, list[dict[str, Any]]]:
    config = load_config(Path("config.yaml")).broker
    sent: list[dict[str, Any]] = []
    info = SimpleNamespace(trade_exemode=2, filling_mode=3, trade_mode=4, volume_step=.01,
                           volume_min=.01, volume_max=100, trade_stops_level=10, point=.00001,
                           trade_freeze_level=20)
    acct = SimpleNamespace(login=config.login, trade_mode=0, trade_allowed=True,
                           trade_expert=True, currency="AUD", leverage=30)
    def send(request: dict[str, Any]) -> Any:
        sent.append(dict(request))
        return SimpleNamespace(retcode=10009, order=123, deal=456)
    api = SimpleNamespace(
        SYMBOL_TRADE_EXECUTION_INSTANT=1, SYMBOL_TRADE_EXECUTION_REQUEST=0,
        SYMBOL_TRADE_EXECUTION_MARKET=2, SYMBOL_FILLING_FOK=1, SYMBOL_FILLING_IOC=2,
        ORDER_FILLING_FOK=0, ORDER_FILLING_IOC=1, ORDER_FILLING_RETURN=2,
        ACCOUNT_TRADE_MODE_DEMO=0, SYMBOL_TRADE_MODE_FULL=4, TRADE_ACTION_DEAL=1,
        ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1, ORDER_TIME_GTC=0,
        TRADE_RETCODE_INVALID_FILL=10030, TRADE_RETCODE_DONE=10009,
        TRADE_RETCODE_DONE_PARTIAL=10010, TRADE_RETCODE_PLACED=10008,
        POSITION_TYPE_BUY=0, TRADE_ACTION_SLTP=6,
        account_info=lambda: acct,
        terminal_info=lambda: SimpleNamespace(connected=True, trade_allowed=True),
        symbol_info=lambda name: info, symbol_select=lambda name, selected: True,
        order_check=lambda request: SimpleNamespace(retcode=0), order_send=send,
        positions_get=lambda: (),
    )
    broker = MT5ExecutionBroker(config, "fixture-not-a-secret", api)
    broker.tick = lambda name: Tick(name, Decimal("1.0999"), Decimal("1.10"), NOW)  # type: ignore[method-assign]
    return broker, api, sent


def intent(broker: MT5ExecutionBroker) -> OrderIntent:
    return OrderIntent("fx-fixture", "candidate", "risk", broker.config.login, "EURUSD", Side.LONG,
                       Decimal(".1"), Decimal("1.10"), Decimal("1.09"), Decimal("1.12"),
                       broker.config.magic_number, NOW)


def test_demo_transport_default_disabled_and_real_accounts_always_refused() -> None:
    broker, api, sent = adapter()
    with pytest.raises(OperatorError, match="disabled"):
        broker.submit(intent(broker))
    broker.demo_execution_enabled = True
    api.account_info().trade_mode = 2
    with pytest.raises(OperatorError, match="Real-money"):
        broker.submit(intent(broker))
    assert not sent


def test_filling_bitmask_and_market_return_exclusion() -> None:
    broker, api, sent = adapter()
    assert filling_modes(api, api.symbol_info("EURUSD")) == (0, 1)
    broker.demo_execution_enabled = True
    original = api.order_send
    def send(request: dict[str, Any]) -> Any:
        result = original(request)
        result.retcode = 10030 if request["type_filling"] == 0 else 10009
        return result
    api.order_send = send
    assert broker.submit(intent(broker)).status == "ACCEPTED"
    assert [r["type_filling"] for r in sent] == [0, 1]
    assert all(r["comment"] == "fx-fixture" for r in sent)


def test_unknown_submit_response_is_never_retried_with_another_filling_mode() -> None:
    broker, api, sent = adapter()
    broker.demo_execution_enabled = True
    original = api.order_send
    def send(request: dict[str, Any]) -> Any:
        result = original(request)
        result.retcode = 10012
        return result
    api.order_send = send
    assert broker.submit(intent(broker)).status == "UNKNOWN"
    assert len(sent) == 1


def test_close_only_and_changed_quote_do_not_send() -> None:
    broker, api, sent = adapter()
    broker.demo_execution_enabled = True
    api.symbol_info("EURUSD").trade_mode = 3
    assert broker.submit(intent(broker)).status == "REJECTED"
    api.symbol_info("EURUSD").trade_mode = 4
    broker.tick = lambda name: Tick(name, Decimal("1.1"), Decimal("1.11"), NOW)  # type: ignore[method-assign]
    assert broker.submit(intent(broker)).code == "QUOTE_CHANGED_REEVALUATE_NEW_DECISION"
    assert not sent


def test_stop_cannot_loosen_or_modify_manual_positions() -> None:
    broker, api, sent = adapter()
    broker.demo_execution_enabled = True
    position = SimpleNamespace(ticket=123, magic=broker.config.magic_number, type=0,
                               sl=1.09, tp=1.12, symbol="EURUSD", volume=.1, comment="fx-fixture")
    api.positions_get = lambda: [position]
    assert broker.modify_position((123, Decimal("1.08"))).code == "STOP_MUST_NOT_LOOSEN"
    assert broker.modify_position((123, Decimal("1.09"))).code == "STOP_ALREADY_APPLIED"
    position.magic = 0
    assert broker.close_position(123).code == "NOT_A_BOT_POSITION"
    assert not sent
