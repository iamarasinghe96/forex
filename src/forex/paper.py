"""Durable simulated broker. The market-data source is never asked to place an order."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from forex.analysis import Side
from forex.broker.base import Broker
from forex.domain import AccountState, Tick, _require_utc
from forex.errors import OperatorError
from forex.execution import (
    QUOTE_FUTURE_TOLERANCE_SECONDS,
    BrokerEvidence,
    BrokerPosition,
    ExecutionSnapshot,
    OrderIntent,
    SubmissionResult,
)
from forex.journal import JournalStore
from forex.risk import protective_stop
from forex.serialization import canonical_json


class PaperBroker:
    def __init__(self, path: Path, feed: Broker, account: AccountState,
                 starting_balance: Decimal, quote_age_seconds: float,
                 reserve_percent: Decimal):
        if (account.currency != "AUD" or not starting_balance.is_finite() or
                starting_balance <= 0 or quote_age_seconds <= 0 or
                not reserve_percent.is_finite() or not 0 <= reserve_percent <= 100):
            raise ValueError("paper broker requires AUD, positive balance/quote age and valid reserve")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path, self.feed, self.account = path, feed, account
        self.quote_age, self.reserve = quote_age_seconds, reserve_percent
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS paper_account (id INTEGER PRIMARY KEY CHECK(id=1),
                    login INTEGER NOT NULL, currency TEXT NOT NULL, balance TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS paper_positions (client_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL, initial_stop TEXT NOT NULL, opened_at TEXT NOT NULL,
                    closed_at TEXT, close_payload TEXT);
            """)
            db.execute("INSERT OR IGNORE INTO paper_account VALUES (1,?,?,?)",
                       (account.login, account.currency, str(starting_balance)))
            row = db.execute("SELECT login,currency FROM paper_account WHERE id=1").fetchone()
            if row != (account.login, account.currency):
                raise OperatorError("Paper database belongs to another account. Use a separate paper database.")

    def _tick(self, symbol: str, now: datetime) -> tuple[Tick, bool]:
        """Latest valid quote and whether it is fresh enough to trade on."""
        _require_utc(now, "now")
        tick = self.feed.tick(symbol)
        if not tick.bid.is_finite() or not tick.ask.is_finite() or not 0 < tick.bid <= tick.ask:
            raise OperatorError("Paper quote is invalid. Halt entries and restore market data.")
        age = (now - tick.time_utc).total_seconds()
        if age < -QUOTE_FUTURE_TOLERANCE_SECONDS:  # Future-dated: a clock fault, not a quiet market.
            raise OperatorError("Paper quote is stale or invalid (future-dated). Check the VPS and MT5 clocks.")
        return tick, age <= self.quote_age

    def _quote(self, symbol: str, now: datetime) -> Tick:
        tick, fresh = self._tick(symbol, now)
        if not fresh:
            raise OperatorError("Paper quote is stale or invalid. Halt entries and restore market data.")
        return tick

    def quote_fresh(self, symbol: str, now: datetime) -> bool:
        """False while a pair has not ticked recently (e.g. the 17:00 New York rollover)."""
        return self._tick(self.feed.resolve_symbol(symbol).broker_name, now)[1]

    def positions(self) -> tuple[BrokerPosition, ...]:
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT payload FROM paper_positions WHERE closed_at IS NULL").fetchall()
        result = []
        for row in rows:
            p = json.loads(row[0])
            result.append(BrokerPosition(p["ticket"], p["client_id"], p["magic"], p["symbol"],
                                         Side(p["side"]), *[Decimal(p[k]) for k in
                                         ("entry", "stop", "target", "volume", "tick_size", "tick_value")]))
        return tuple(result)

    def _pnl(self, position: BrokerPosition, price: Decimal) -> Decimal:
        spec = self.feed.resolve_symbol(position.symbol)
        if spec.tick_size <= 0 or spec.tick_value <= 0:
            raise OperatorError("Paper valuation lacks a valid account-currency tick value.")
        direction = Decimal(1) if position.side is Side.LONG else Decimal(-1)
        return (price - position.entry) * direction / spec.tick_size * spec.tick_value * position.volume

    def state(self, now: datetime) -> AccountState:
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT balance FROM paper_account WHERE id=1").fetchone()
        balance = Decimal(row[0])
        unrealized = Decimal(0)
        for p in self.positions():
            tick = self._tick(p.symbol, now)[0]  # Last valid price; quiet markets do not stop valuation.
            unrealized += self._pnl(p, tick.bid if p.side is Side.LONG else tick.ask)
        return replace(self.account, balance=balance, equity=balance + unrealized)

    def openings(self) -> dict[str, tuple[str, Decimal]]:
        """Opening time (UTC ISO) and initial stop of every open position, by client id."""
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT client_id,opened_at,initial_stop FROM paper_positions "
                              "WHERE closed_at IS NULL").fetchall()
        return {row[0]: (row[1], Decimal(row[2])) for row in rows}

    def position_status(self, now: datetime) -> tuple[dict[str, Any], ...]:
        result = []
        openings = self.openings()
        for position in self.positions():
            tick = self._tick(position.symbol, now)[0]
            price = tick.bid if position.side is Side.LONG else tick.ask
            opened_at, initial_stop = openings.get(position.client_id, ("", position.stop))
            risk = abs(position.entry - initial_stop)
            sign = 1 if position.side is Side.LONG else -1
            result.append({**json.loads(canonical_json(position)), "market_price": str(price),
                           "unrealized_pnl_aud": str(self._pnl(position, price)),
                           "opened_at_utc": opened_at, "initial_stop": str(initial_stop),
                           # Open profit in multiples of the initial risk (1R = the loss at the first stop).
                           "r_multiple": str(((price - position.entry) * sign / risk).quantize(Decimal("0.01")))
                           if risk > 0 else None,
                           "pnl_basis": "simulated_incomplete_costs"})
        return tuple(result)

    def snapshot(self, symbol: str, now: datetime) -> ExecutionSnapshot:
        spec = self.feed.resolve_symbol(symbol)
        tick, fresh = self._tick(spec.broker_name, now)
        # A momentarily old quote blocks entries for this pair instead of failing the whole cycle.
        return ExecutionSnapshot(self.state(now), spec, tick, self.positions(), True,
                                 fresh and self.feed.market_allows_entries(spec.broker_name), now)

    def submit(self, intent: OrderIntent) -> SubmissionResult:
        if not self.feed.market_allows_entries(intent.symbol):
            return SubmissionResult("REJECTED", None, "PAPER_MARKET_ENTRY_PERMISSION_BLOCKED")
        tick = self._quote(intent.symbol, intent.created_at_utc)
        price = tick.ask if intent.side is Side.LONG else tick.bid
        if price != intent.entry:
            return SubmissionResult("REJECTED", None, "PAPER_QUOTE_CHANGED")
        spec = self.feed.resolve_symbol(intent.symbol)
        position = BrokerPosition(intent.client_id, intent.client_id, intent.magic, intent.symbol,
                                  intent.side, price, intent.stop, intent.target, intent.volume,
                                  spec.tick_size, spec.tick_value)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR IGNORE INTO paper_positions VALUES (?,?,?,?,NULL,NULL)",
                       (intent.client_id, canonical_json(position), str(intent.stop),
                        intent.created_at_utc.isoformat()))
        return SubmissionResult("ACCEPTED", intent.client_id, "PAPER_SIMULATED_FILL")

    def evidence(self, start: datetime, end: datetime) -> tuple[BrokerEvidence, ...]:
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT client_id,closed_at FROM paper_positions WHERE opened_at<=?",
                              (end.isoformat(),)).fetchall()
        return tuple(BrokerEvidence(row[0], row[0], "POSITION" if row[1] is None else "DEAL")
                     for row in rows)

    def close(self, position: BrokerPosition, price: Decimal, now: datetime, reason: str) -> None:
        pnl = self._pnl(position, price)
        spec = self.feed.resolve_symbol(position.symbol)
        pips = (price - position.entry) / spec.pip_size * (1 if position.side is Side.LONG else -1)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT opened_at,closed_at FROM paper_positions WHERE client_id=?",
                             (position.client_id,)).fetchone()
            if row is None or row[1] is not None:
                return
            old = db.execute("SELECT balance FROM paper_account WHERE id=1").fetchone()
            balance = Decimal(old[0]) + pnl
            payload = {"position": position, "symbol": position.symbol, "entry": position.entry,
                       "exit": price, "volume": position.volume, "opened_at_utc": row[0],
                       "closed_at_utc": now, "pnl_aud": pnl, "balance": balance,
                       "pips": pips, "direction": position.side,
                       "reserve_percent": self.reserve, "reason": reason,
                       "pnl_basis": "simulated_incomplete_costs", "costs_complete": False,
                       "limitations": "Observed quotes only; tick-value approximation; commission, swap, slippage and missed intra-poll paths unavailable."}
            db.execute("UPDATE paper_positions SET closed_at=?,close_payload=? WHERE client_id=?",
                       (now.isoformat(), canonical_json(payload), position.client_id))
            db.execute("UPDATE paper_account SET balance=? WHERE id=1", (str(balance),))

    def manage(self, now: datetime, *, flatten: bool = False,
               atr_by_symbol: dict[str, Decimal] | None = None,
               atr_multiple: Decimal | None = None) -> None:
        for p in self.positions():
            tick, fresh = self._tick(p.symbol, now)
            if not fresh:
                if flatten:
                    raise OperatorError("Paper quote is stale or invalid. Halt entries and restore market data.")
                continue  # Re-checked next cycle; stops are not judged on an old price.
            price = tick.bid if p.side is Side.LONG else tick.ask
            stop_hit = price <= p.stop if p.side is Side.LONG else price >= p.stop
            target_hit = price >= p.target if p.side is Side.LONG else price <= p.target
            if flatten or stop_hit or target_hit:
                self.close(p, price, now, "FLATTEN" if flatten else "STOP" if stop_hit else "TARGET")
                continue
            with closing(sqlite3.connect(self.path)) as db, db:
                row = db.execute("SELECT initial_stop FROM paper_positions WHERE client_id=?",
                                 (p.client_id,)).fetchone()
                atr = (atr_by_symbol or {}).get(p.symbol, Decimal(0))
                result = protective_stop(p.side, p.entry, Decimal(row[0]), p.stop, price,
                                         atr, atr_multiple if atr > 0 else None)
                db.execute("UPDATE paper_positions SET payload=? WHERE client_id=? AND closed_at IS NULL",
                           (canonical_json(replace(p, stop=result.stop)), p.client_id))

    def journal_fills(self, journal: JournalStore) -> None:
        """Replay durable fills after crashes; journal identities prevent double counting."""
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT client_id,payload,opened_at,closed_at,close_payload,initial_stop FROM paper_positions").fetchall()
        for identity, payload, opened, closed, close_payload, initial_stop in rows:
            # Opening evidence is immutable even after protective stops move.
            position: dict[str, Any] = json.loads(payload)
            provenance = self._decision_provenance(identity)
            opening = {**position, "stop": initial_stop, **provenance}
            journal.append("PAPER", "trade_opened", identity, opening, datetime.fromisoformat(opened))
            if closed:
                journal.append("PAPER", "trade_closed", identity, {**json.loads(close_payload), **provenance},
                               datetime.fromisoformat(closed))

    def _decision_provenance(self, identity: str) -> dict[str, Any]:
        with closing(sqlite3.connect(self.path)) as db, db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='execution_intents'").fetchone():
                return {"decision_provenance": "UNAVAILABLE_STANDALONE_SIMULATION"}
            row = db.execute("SELECT payload_json FROM execution_intents WHERE client_id=?", (identity,)).fetchone()
            if row is None:
                return {"decision_provenance": "UNAVAILABLE_STANDALONE_SIMULATION"}
            intent = json.loads(row[0])
            records = db.execute("SELECT kind,payload_json FROM journal_events WHERE mode='PAPER' AND entity_id=? AND kind IN ('candidate','risk_decision','context_review') ORDER BY sequence",
                                 (intent["candidate_id"],)).fetchall()
        evidence = {kind: json.loads(value) for kind, value in records}
        return {"decision_provenance": evidence, "intent": intent, "timeframe": "H1",
                "trade_style": evidence.get("candidate", {}).get("trade_style")}
