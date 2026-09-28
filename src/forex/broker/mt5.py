"""MetaTrader 5 adapter with dynamic symbols and runtime currency conversion."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from types import ModuleType
from typing import Any

from forex.broker.base import Broker
from forex.broker.ic_markets_clock import (
    server_timestamp_to_utc,
    utc_to_server_datetime,
    validate_live_server_timestamp,
)
from forex.config import BrokerConfig
from forex.domain import AccountMode, AccountState, Candle, SymbolSpec, Tick, Timeframe
from forex.errors import OperatorError


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


class MT5Broker(Broker):
    """Translate the Windows MT5 Python API into the broker-neutral interface."""

    def __init__(self, config: BrokerConfig, password: str, api: ModuleType | Any | None = None):
        if api is None:
            try:
                import MetaTrader5 as api_module
            except ImportError as exc:
                raise OperatorError(
                    "MetaTrader5 is not installed. On the Windows VPS run "
                    "`python -m pip install -e .[mt5]`, then retry."
                ) from exc
            api = api_module
        self.api = api
        self.config = config
        self.password = password
        self._last_tick_timestamp: float | None = None

    def connect(self) -> AccountState:
        args: dict[str, object] = {
            "login": self.config.login,
            "password": self.password,
            "server": self.config.server,
            "timeout": self.config.connect_timeout_seconds * 1000,
        }
        if self.config.terminal_path:
            args["path"] = self.config.terminal_path
        if not self.api.initialize(**args):
            code, detail = self.api.last_error()
            raise OperatorError(
                f"MT5 connection failed ({code}: {detail}). Open MT5, confirm it is logged into "
                f"account {self.config.login} on {self.config.server}, check the password in .env, "
                "then run verification again."
            )
        terminal = self.api.terminal_info()
        if terminal is None:
            raise OperatorError("MT5 returned no terminal status. Restart MT5 and retry verification.")
        if not terminal.connected:
            raise OperatorError(
                "MT5 is open but disconnected. Check the VPS internet connection and the connection "
                "indicator in the lower-right of MT5, then retry."
            )
        if not terminal.trade_allowed:
            raise OperatorError(
                "MT5 AutoTrading is disabled by the client (the condition behind retcode 10027). "
                "In MT5 press the 'Algo Trading' toolbar button until it is enabled, then retry."
            )
        info = self.api.account_info()
        if info is None:
            raise OperatorError("MT5 returned no account details. Log in again in MT5, then retry.")
        if info.currency != self.config.account_currency:
            raise OperatorError(
                f"MT5 reports account currency {info.currency}, but config.yaml expects "
                f"{self.config.account_currency}. Verify the account and correct account_currency."
            )
        if int(info.leverage) > 30:
            raise OperatorError(
                f"MT5 account leverage is 1:{info.leverage}, above the configured ASIC cap of 1:30. "
                "Ask IC Markets to change the account to 1:30 before using this bot."
            )
        hedge_value = getattr(self.api, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2)
        mode = AccountMode.HEDGING if info.margin_mode == hedge_value else AccountMode.NETTING
        return AccountState(
            login=int(info.login), currency=str(info.currency), balance=_decimal(info.balance),
            equity=_decimal(info.equity), leverage=int(info.leverage), mode=mode,
        )

    def disconnect(self) -> None:
        self.api.shutdown()

    def resolve_symbol(self, requested: str) -> SymbolSpec:
        target = requested.upper()
        candidates = [s for s in (self.api.symbols_get() or ()) if str(s.name).upper() == target]
        if not candidates:
            candidates = [s for s in (self.api.symbols_get() or ()) if str(s.name).upper().startswith(target)]
        if not candidates:
            raise OperatorError(
                f"Broker symbol {requested} was not found, including suffix variants. In MT5 open "
                "Market Watch, right-click, choose 'Show All', then retry."
            )
        candidates.sort(key=lambda item: (len(str(item.name)), str(item.name)))
        name = str(candidates[0].name)
        if not self.api.symbol_select(name, True):
            raise OperatorError(
                f"MT5 refused to select {name}. Enable it in Market Watch and retry verification."
            )
        info = self.api.symbol_info(name)
        if info is None:
            raise OperatorError(f"MT5 lost symbol details for {name}. Reconnect MT5 and retry.")
        return SymbolSpec(
            requested_name=requested, broker_name=name, base_currency=str(info.currency_base),
            profit_currency=str(info.currency_profit), digits=int(info.digits), point=_decimal(info.point),
            tick_size=_decimal(info.trade_tick_size), tick_value=_decimal(info.trade_tick_value),
            contract_size=_decimal(info.trade_contract_size), volume_min=_decimal(info.volume_min),
            volume_max=_decimal(info.volume_max), volume_step=_decimal(info.volume_step),
            stops_level_points=int(info.trade_stops_level),
            freeze_level_points=int(info.trade_freeze_level), filling_mode=int(info.filling_mode),
        )

    def tick(self, broker_symbol: str) -> Tick:
        raw = self.api.symbol_info_tick(broker_symbol)
        if raw is None:
            raise OperatorError(
                f"No live tick is available for {broker_symbol}. Confirm Market Watch shows live prices "
                "and the market is open, then retry."
            )
        self._last_tick_timestamp = float(raw.time_msc) / 1000
        timestamp = server_timestamp_to_utc(self._last_tick_timestamp)
        return Tick(broker_symbol, _decimal(raw.bid), _decimal(raw.ask), timestamp)

    def validate_server_clock(self, now: datetime, tolerance_seconds: int) -> None:
        """Validate the most recently retrieved live tick against the system UTC clock."""
        if self._last_tick_timestamp is None:
            raise OperatorError("Retrieve an MT5 tick before validating the broker server clock.")
        validate_live_server_timestamp(
            self._last_tick_timestamp,
            now,
            timedelta(seconds=tolerance_seconds),
        )

    def pip_value_per_lot(self, spec: SymbolSpec, account_currency: str) -> Decimal:
        """Compute one-lot pip value from contract properties and a live conversion quote."""
        profit_value = spec.contract_size * spec.pip_size
        if spec.profit_currency == account_currency:
            return profit_value
        rate = self._conversion_rate(spec.profit_currency, account_currency)
        converted = profit_value * rate
        if spec.tick_size <= 0 or spec.tick_value <= 0 or spec.contract_size <= 0:
            raise OperatorError(
                f"MT5 supplied invalid tick properties for {spec.broker_name}. Do not trade it; "
                "contact the broker and retry after its symbol specification is corrected."
            )
        return converted

    def _conversion_rate(self, source: str, destination: str) -> Decimal:
        direct = f"{source}{destination}"
        inverse = f"{destination}{source}"
        try:
            spec = self.resolve_symbol(direct)
            tick = self.tick(spec.broker_name)
            return (tick.bid + tick.ask) / Decimal(2)
        except OperatorError:
            pass
        try:
            spec = self.resolve_symbol(inverse)
            tick = self.tick(spec.broker_name)
            midpoint = (tick.bid + tick.ask) / Decimal(2)
            if midpoint <= 0:
                raise ArithmeticError
            return Decimal(1) / midpoint
        except (OperatorError, ArithmeticError) as exc:
            raise OperatorError(
                f"Cannot convert {source} profit into {destination}: neither {direct} nor {inverse} "
                "has a usable live quote. Add the conversion pair to MT5 Market Watch, then retry."
            ) from exc

    def timeframe_constant(self, timeframe: Timeframe) -> int:
        """Map broker-neutral timeframes explicitly to MT5 constants."""
        mapping = {
            Timeframe.H1: self.api.TIMEFRAME_H1,
            Timeframe.H4: self.api.TIMEFRAME_H4,
        }
        return int(mapping[timeframe])

    def candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> list[Candle]:
        return self._candles(symbol, timeframe, start, end, allow_empty=False)

    def _candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime,
        *, allow_empty: bool, retries: int = 3,
    ) -> list[Candle]:
        for label, value in (("start", start), ("end", end)):
            if value.tzinfo is None or value.utcoffset() is None or value.utcoffset() != timedelta(0):
                raise OperatorError(f"Candle {label} must be a UTC-aware datetime.")
        if start >= end:
            raise OperatorError("Candle start must be earlier than end.")
        resolved = self.resolve_symbol(symbol)
        server_start = utc_to_server_datetime(start)
        server_end = utc_to_server_datetime(end)
        rows: Any = None
        for _ in range(retries):
            rows = self.api.copy_rates_range(
                resolved.broker_name, self.timeframe_constant(timeframe), server_start, server_end
            )
            if rows is not None and len(rows) > 0:
                break
        if rows is None or len(rows) == 0:
            if allow_empty:
                return []
            code, detail = self.api.last_error()
            raise OperatorError(
                f"MT5 returned no {timeframe.value} candles for {symbol} after {retries} attempts "
                f"({code}: {detail}). Check the market connection, open the chart, increase "
                "Tools > Options > Charts > Max bars in chart, and retry."
            )
        by_time: dict[datetime, Candle] = {}
        try:
            for row in rows:
                timestamp = server_timestamp_to_utc(float(row["time"]))
                candle = Candle.from_values(
                    symbol.upper(), timeframe, timestamp, row["open"], row["high"], row["low"],
                    row["close"], row["tick_volume"], row["spread"], row["real_volume"],
                )
                by_time[timestamp] = candle
        except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
            raise OperatorError(
                f"MT5 returned malformed {timeframe.value} candle data for {symbol}: {exc}. "
                "Reconnect MT5 and do not use this data."
            ) from exc
        return [by_time[key] for key in sorted(by_time)]

    # Trading methods remain deliberately unavailable; Layer 2 is read-only.

    def place_order(self, request: Any) -> Any:
        raise NotImplementedError("Order placement is implemented in Layer 7; Layer 1 cannot trade.")

    def modify_position(self, request: Any) -> Any:
        raise NotImplementedError("Position modification is implemented in Layer 7.")

    def close_position(self, request: Any) -> Any:
        raise NotImplementedError("Position closing is implemented in Layer 7.")

    def open_positions(self) -> list[Any]:
        raise NotImplementedError("Position reconciliation is implemented in Layer 7.")

    def account_state(self) -> AccountState:
        info = self.api.account_info()
        if info is None:
            raise OperatorError("MT5 returned no account state. Reconnect MT5 and retry.")
        hedge_value = getattr(self.api, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2)
        return AccountState(int(info.login), str(info.currency), _decimal(info.balance),
                            _decimal(info.equity), int(info.leverage),
                            AccountMode.HEDGING if info.margin_mode == hedge_value else AccountMode.NETTING)

    def history(self, start: datetime, end: datetime) -> list[Any]:
        raise NotImplementedError("Broker history is implemented in Layer 7.")
