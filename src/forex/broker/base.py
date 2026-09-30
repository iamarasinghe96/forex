"""Broker boundary. Later layers depend only on this interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from forex.domain import AccountState, Candle, SymbolSpec, Tick, Timeframe


class Broker(ABC):
    def market_allows_entries(self, broker_symbol: str) -> bool:
        """Unknown market permission is not permission to enter, including in paper mode."""
        return False

    @abstractmethod
    def connect(self) -> AccountState: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def resolve_symbol(self, requested: str) -> SymbolSpec: ...

    @abstractmethod
    def tick(self, broker_symbol: str) -> Tick: ...

    @abstractmethod
    def pip_value_per_lot(self, spec: SymbolSpec, account_currency: str) -> Decimal: ...

    @abstractmethod
    def candles(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> Sequence[Candle]: ...

    @abstractmethod
    def place_order(self, request: Any) -> Any: ...

    @abstractmethod
    def modify_position(self, request: Any) -> Any: ...

    @abstractmethod
    def close_position(self, request: Any) -> Any: ...

    @abstractmethod
    def open_positions(self) -> Sequence[Any]: ...

    @abstractmethod
    def account_state(self) -> AccountState: ...

    @abstractmethod
    def history(self, start: datetime, end: datetime) -> Sequence[Any]: ...
