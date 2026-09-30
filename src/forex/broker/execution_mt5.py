"""Explicitly enabled demo-only MT5 execution; real-money accounts are refused."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from forex.analysis import Side
from forex.broker.ic_markets_clock import utc_to_server_datetime
from forex.broker.mt5 import MT5Broker, _decimal
from forex.domain import AccountState
from forex.errors import OperatorError
from forex.execution import (
    BrokerEvidence,
    BrokerPosition,
    ExecutionSnapshot,
    OrderIntent,
    SubmissionResult,
)


def filling_modes(api: Any, info: Any) -> tuple[int, ...]:
    """SYMBOL_FILLING_MODE is a bitmask; ORDER_FILLING values are different enums."""
    modes = []
    instant = info.trade_exemode in (api.SYMBOL_TRADE_EXECUTION_INSTANT,
                                    api.SYMBOL_TRADE_EXECUTION_REQUEST)
    if instant or info.filling_mode & api.SYMBOL_FILLING_FOK:
        modes.append(int(api.ORDER_FILLING_FOK))
    if instant or info.filling_mode & api.SYMBOL_FILLING_IOC:
        modes.append(int(api.ORDER_FILLING_IOC))
    if info.trade_exemode != api.SYMBOL_TRADE_EXECUTION_MARKET:
        modes.append(int(api.ORDER_FILLING_RETURN))
    return tuple(modes)


class MT5ExecutionBroker(MT5Broker):
    """No command enables this automatically; credentials and demo verification are deferred."""

    demo_execution_enabled: bool = False

    def connect(self) -> AccountState:
        account = super().connect()
        terminal = self.api.terminal_info()
        if terminal is None or not terminal.trade_allowed:
            raise OperatorError(
                "MT5 AutoTrading is disabled by the client (the condition behind retcode 10027). "
                "In MT5 press the 'Algo Trading' toolbar button until it is enabled, then retry."
            )
        return account

    def _guard(self) -> None:
        account, terminal = self.api.account_info(), self.api.terminal_info()
        if not self.demo_execution_enabled:
            raise OperatorError("Demo execution is disabled. Complete the operator setup checklist first.")
        if account is None or terminal is None or not terminal.connected:
            raise OperatorError("MT5 is disconnected. Reconnect and reconcile before orders.")
        if int(account.login) != self.config.login:
            raise OperatorError("MT5 account changed. Restore the configured demo account and reconcile.")
        if account.trade_mode != self.api.ACCOUNT_TRADE_MODE_DEMO:
            raise OperatorError("Real-money execution is outside this build and is refused.")
        if not terminal.trade_allowed or not account.trade_allowed or account.trade_expert is False:
            raise OperatorError("AutoTrading disabled. Check MT5 Algo Trading and account permissions.")
        if account.currency != self.config.account_currency or account.leverage > 30:
            raise OperatorError("Account currency/leverage mismatch. Restore configured currency and <=1:30.")

    def open_positions(self) -> list[Any]:
        rows = self.api.positions_get()
        if rows is None:
            raise OperatorError("MT5 position query failed. Halt entries and reconnect; do not assume flat.")
        return list(rows)

    def history(self, start: datetime, end: datetime) -> list[Any]:
        rows = self.api.history_deals_get(utc_to_server_datetime(start), utc_to_server_datetime(end))
        if rows is None:
            raise OperatorError("MT5 deal history unavailable. Keep unresolved submissions blocked.")
        return list(rows)

    def snapshot(self, symbol: str, now: datetime) -> ExecutionSnapshot:
        account, spec = self.account_state(), self.resolve_symbol(symbol)
        tick = self.tick(spec.broker_name)
        positions = []
        for position in self.open_positions():
            position_spec = self.resolve_symbol(str(position.symbol))
            positions.append(BrokerPosition(
                str(position.ticket), str(position.comment), int(position.magic),
                str(position.symbol), Side.LONG if position.type == self.api.POSITION_TYPE_BUY
                else Side.SHORT, _decimal(position.price_open), _decimal(position.sl),
                _decimal(position.tp), _decimal(position.volume), position_spec.tick_size,
                position_spec.tick_value,
            ))
        orders = self.api.orders_get()
        terminal = self.api.terminal_info()
        info = self.api.symbol_info(spec.broker_name)
        if orders is None or terminal is None or info is None:
            raise OperatorError("MT5 state incomplete. Halt entries and reconcile all orders/positions.")
        return ExecutionSnapshot(account, spec, tick, tuple(positions), bool(terminal.connected),
                                 bool(self.demo_execution_enabled and terminal.trade_allowed and not orders and
                                      info.trade_mode == self.api.SYMBOL_TRADE_MODE_FULL), now)

    def evidence(self, start: datetime, end: datetime) -> tuple[BrokerEvidence, ...]:
        orders = self.api.orders_get()
        old_orders = self.api.history_orders_get(utc_to_server_datetime(start),
                                                 utc_to_server_datetime(end))
        if orders is None or old_orders is None:
            raise OperatorError("MT5 order history unavailable. Do not retry unresolved submissions.")
        result = []
        for kind, rows in (("POSITION", self.open_positions()),
                           ("ORDER", list(orders) + list(old_orders)),
                           ("DEAL", self.history(start, end))):
            for row in rows:
                if int(row.magic) == self.config.magic_number and str(row.comment).startswith("fx-"):
                    result.append(BrokerEvidence(str(row.comment), str(row.ticket), kind))  # type: ignore[arg-type]
        return tuple(result)

    def _send(self, request: dict[str, Any], info: Any) -> SubmissionResult:
        modes = filling_modes(self.api, info)
        if not modes:
            return SubmissionResult("REJECTED", None, "NO_SUPPORTED_FILLING_MODE")
        for filling in modes:
            request["type_filling"] = filling
            check = self.api.order_check(request)
            if check is None:
                return SubmissionResult("REJECTED", None, "ORDER_CHECK_UNAVAILABLE_NO_SEND")
            if check.retcode == self.api.TRADE_RETCODE_INVALID_FILL:
                continue
            if check.retcode != 0:
                return SubmissionResult("REJECTED", None, f"ORDER_CHECK_{check.retcode}")
            result = self.api.order_send(request)
            if result is None:
                return SubmissionResult("UNKNOWN", None, "NO_SUBMISSION_RESPONSE_RECONCILE")
            code = int(result.retcode)
            if code == self.api.TRADE_RETCODE_INVALID_FILL:
                continue  # Definitive rejection only; safe to try a different allowed filling mode.
            ticket = str(result.order or result.deal) if result.order or result.deal else None
            if code == self.api.TRADE_RETCODE_DONE_PARTIAL:
                return SubmissionResult("PARTIAL", ticket, "PARTIAL_FILL_RECONCILE")
            if code in (self.api.TRADE_RETCODE_DONE, self.api.TRADE_RETCODE_PLACED):
                return SubmissionResult("ACCEPTED", ticket, "BROKER_ACCEPTED_RECONCILE")
            # MetaQuotes documented rejection codes. Unrecognized/timeout/connection
            # results remain UNKNOWN, never an automatic retry.
            if code in {10004, 10006, 10013, 10014, 10015, 10016, 10017, 10018, 10019,
                        10020, 10021, 10022, 10024, 10026, 10027, 10033, 10034,
                        10035, 10042, 10043, 10044, 10045, 10046}:
                reason = {10027: "AUTOTRADING_DISABLED_CHECK_ALGO_TRADING_BUTTON",
                          10044: "BROKER_CLOSE_ONLY_HALT_ENTRIES"}.get(code, f"REJECTED_{code}")
                return SubmissionResult("REJECTED", ticket, reason)
            return SubmissionResult("UNKNOWN", ticket, f"RETCODE_{code}_RECONCILE")
        return SubmissionResult("REJECTED", None, "ALL_ALLOWED_FILLING_MODES_REJECTED")

    def submit(self, intent: OrderIntent) -> SubmissionResult:
        self._guard()
        if intent.account_login != self.config.login or intent.magic != self.config.magic_number:
            return SubmissionResult("REJECTED", None, "ACCOUNT_OR_MAGIC_MISMATCH")
        info = self.api.symbol_info(intent.symbol)
        if info is None or not self.api.symbol_select(intent.symbol, True):
            return SubmissionResult("REJECTED", None, "SYMBOL_UNAVAILABLE")
        if info.trade_mode != self.api.SYMBOL_TRADE_MODE_FULL:
            return SubmissionResult("REJECTED", None, "BROKER_ENTRY_PERMISSION_RESTRICTED")
        tick = self.tick(intent.symbol)
        price = tick.ask if intent.side is Side.LONG else tick.bid
        if price != intent.entry:
            return SubmissionResult("REJECTED", None, "QUOTE_CHANGED_REEVALUATE_NEW_DECISION")
        step = _decimal(info.volume_step)
        if (not intent.volume.is_finite() or step <= 0 or
                not _decimal(info.volume_min) <= intent.volume <= _decimal(info.volume_max) or
                intent.volume % step != 0):
            return SubmissionResult("REJECTED", None, "INVALID_VOLUME")
        sign = Decimal(1) if intent.side is Side.LONG else Decimal(-1)
        risk = sign * (price - intent.stop)
        minimum = _decimal(info.trade_stops_level) * _decimal(info.point)
        close_price = tick.bid if intent.side is Side.LONG else tick.ask
        if (risk <= 0 or sign * (close_price - intent.stop) < minimum or
                sign * (intent.target - price) < max(minimum, risk * Decimal("1.5"))):
            return SubmissionResult("REJECTED", None, "INVALID_STOPS_OR_RR")
        return self._send({"action": self.api.TRADE_ACTION_DEAL, "symbol": intent.symbol,
                           "volume": float(intent.volume), "type": self.api.ORDER_TYPE_BUY
                           if intent.side is Side.LONG else self.api.ORDER_TYPE_SELL,
                           "price": float(price), "sl": float(intent.stop), "tp": float(intent.target),
                           "magic": intent.magic, "comment": intent.client_id,
                           "type_time": self.api.ORDER_TIME_GTC}, info)

    def place_order(self, request: Any) -> SubmissionResult:
        if not isinstance(request, OrderIntent):
            raise TypeError("Layer 7 placement requires a validated OrderIntent")
        return self.submit(request)

    def modify_position(self, request: Any) -> SubmissionResult:
        """Request is (broker ticket, tighter stop); target cannot be changed here."""
        self._guard()
        ticket, new_stop = request
        positions = [p for p in self.open_positions() if p.ticket == int(ticket)]
        if not positions:
            return SubmissionResult("REJECTED", None, "POSITION_NO_LONGER_OPEN")
        position = positions[0]
        if position.magic != self.config.magic_number:
            return SubmissionResult("REJECTED", None, "NOT_A_BOT_POSITION")
        stop = Decimal(str(new_stop))
        previous = _decimal(position.sl)
        side = Side.LONG if position.type == self.api.POSITION_TYPE_BUY else Side.SHORT
        sign = Decimal(1) if side is Side.LONG else Decimal(-1)
        if not stop.is_finite() or stop <= 0 or (previous > 0 and sign * (stop - previous) < 0):
            return SubmissionResult("REJECTED", None, "STOP_MUST_NOT_LOOSEN")
        if stop == previous:
            return SubmissionResult("ACCEPTED", str(ticket), "STOP_ALREADY_APPLIED")
        info, tick = self.api.symbol_info(position.symbol), self.tick(position.symbol)
        if info is None:
            return SubmissionResult("REJECTED", None, "SYMBOL_UNAVAILABLE")
        price = tick.bid if side is Side.LONG else tick.ask
        minimum = _decimal(max(info.trade_stops_level, info.trade_freeze_level)) * _decimal(info.point)
        if sign * (price - stop) < minimum:
            return SubmissionResult("REJECTED", None, "STOP_OR_FREEZE_DISTANCE")
        result = self.api.order_send({"action": self.api.TRADE_ACTION_SLTP,
                                      "position": int(ticket), "symbol": position.symbol,
                                      "sl": float(stop), "tp": float(position.tp),
                                      "magic": self.config.magic_number})
        if result is not None and result.retcode == self.api.TRADE_RETCODE_DONE:
            return SubmissionResult("ACCEPTED", str(ticket), "STOP_UPDATE_RECONCILE")
        return SubmissionResult("UNKNOWN", str(ticket), "STOP_UPDATE_RECONCILE_BEFORE_RETRY")

    def close_position(self, request: Any) -> SubmissionResult:
        """Close the currently observed bot ticket only; no reversal or guessed volume."""
        self._guard()
        positions = [p for p in self.open_positions() if p.ticket == int(request)]
        if not positions:
            return SubmissionResult("ACCEPTED", str(request), "POSITION_ALREADY_CLOSED")
        position = positions[0]
        if position.magic != self.config.magic_number:
            return SubmissionResult("REJECTED", None, "NOT_A_BOT_POSITION")
        info, tick = self.api.symbol_info(position.symbol), self.tick(position.symbol)
        if info is None:
            return SubmissionResult("REJECTED", None, "SYMBOL_UNAVAILABLE")
        long = position.type == self.api.POSITION_TYPE_BUY
        return self._send({"action": self.api.TRADE_ACTION_DEAL, "position": int(request),
                           "symbol": position.symbol, "volume": float(position.volume),
                           "type": self.api.ORDER_TYPE_SELL if long else self.api.ORDER_TYPE_BUY,
                           "price": float(tick.bid if long else tick.ask),
                           "magic": self.config.magic_number, "comment": str(position.comment),
                           "type_time": self.api.ORDER_TIME_GTC}, info)
