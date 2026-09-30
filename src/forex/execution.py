"""Durable submission identities and broker-authoritative reconciliation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Literal, Protocol

from forex.analysis import Side, TradeCandidate
from forex.context import ContextDecision
from forex.domain import AccountMode, AccountState, SymbolSpec, Tick, _require_utc
from forex.errors import OperatorError
from forex.persistence import RiskSessionStore
from forex.risk import (
    DecisionStatus,
    OpenRiskPosition,
    PortfolioRiskState,
    RiskDecision,
    RiskPolicy,
    decide_risk,
    enforce_layer6_ceiling,
    evaluate_daily_risk,
)


@dataclass(frozen=True)
class BrokerPosition:
    ticket: str
    client_id: str
    magic: int
    symbol: str
    side: Side
    entry: Decimal
    stop: Decimal
    target: Decimal
    volume: Decimal
    tick_size: Decimal
    tick_value: Decimal

    def risk_position(self) -> OpenRiskPosition:
        if self.stop <= 0:
            raise OperatorError("An open position has no protective stop. Halt entries and review MT5.")
        return OpenRiskPosition(self.symbol, self.side, self.entry, self.stop, self.volume,
                                self.tick_size, self.tick_value)


@dataclass(frozen=True)
class ExecutionSnapshot:
    account: AccountState
    spec: SymbolSpec
    tick: Tick
    positions: tuple[BrokerPosition, ...]
    connected: bool
    entries_allowed: bool
    observed_at_utc: datetime


@dataclass(frozen=True)
class OrderIntent:
    client_id: str
    candidate_id: str
    risk_decision_id: str
    account_login: int
    symbol: str
    side: Side
    volume: Decimal
    entry: Decimal
    stop: Decimal
    target: Decimal
    magic: int
    created_at_utc: datetime


@dataclass(frozen=True)
class SubmissionResult:
    status: Literal["ACCEPTED", "PARTIAL", "REJECTED", "UNKNOWN"]
    ticket: str | None
    code: str


@dataclass(frozen=True)
class BrokerEvidence:
    client_id: str
    ticket: str
    kind: Literal["POSITION", "ORDER", "DEAL"]


class ExecutionBroker(Protocol):
    def snapshot(self, symbol: str, now: datetime) -> ExecutionSnapshot: ...
    def submit(self, intent: OrderIntent) -> SubmissionResult: ...
    def evidence(self, start: datetime, end: datetime) -> tuple[BrokerEvidence, ...]: ...


@dataclass(frozen=True)
class ExecutionRecord:
    client_id: str
    state: str
    ticket: str | None
    detail: str


class ExecutionStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS execution_intents (
                client_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, state TEXT NOT NULL,
                ticket TEXT, detail TEXT NOT NULL, updated_at_utc TEXT NOT NULL)""")

    def get(self, client_id: str) -> ExecutionRecord | None:
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT client_id,state,ticket,detail FROM execution_intents "
                             "WHERE client_id=?", (client_id,)).fetchone()
        return ExecutionRecord(*row) if row else None

    def reserve(self, intent: OrderIntent) -> bool:
        """Only the winner of the unique insertion may submit; commit before network I/O."""
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute("SELECT 1 FROM execution_intents WHERE state IN "
                                 "('IN_FLIGHT','UNKNOWN','ACCEPTED','PARTIAL') LIMIT 1").fetchone()
            if pending:
                return False
            cursor = db.execute("INSERT OR IGNORE INTO execution_intents VALUES (?,?,?,?,?,?)", (
                intent.client_id, json.dumps(asdict(intent), default=str, sort_keys=True),
                "IN_FLIGHT", None, "Submission reserved; reconcile before any retry.",
                intent.created_at_utc.isoformat(),
            ))
            return cursor.rowcount == 1

    def update(self, client_id: str, state: str, ticket: str | None, detail: str,
               now: datetime) -> ExecutionRecord:
        _require_utc(now, "now")
        with closing(sqlite3.connect(self.path)) as db, db:
            changed = db.execute("UPDATE execution_intents SET state=?,ticket=?,detail=?,"
                                 "updated_at_utc=? WHERE client_id=?",
                                 (state, ticket, detail, now.isoformat(), client_id))
            if changed.rowcount != 1:
                raise ValueError("unknown execution identity")
        return ExecutionRecord(client_id, state, ticket, detail)

    def unresolved(self) -> tuple[str, ...]:
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT client_id FROM execution_intents "
                              "WHERE state IN ('IN_FLIGHT','UNKNOWN','ACCEPTED','PARTIAL')").fetchall()
        return tuple(str(row[0]) for row in rows)


class ExecutionService:
    def __init__(self, broker: ExecutionBroker, store: ExecutionStore,
                 sessions: RiskSessionStore, policy: RiskPolicy, magic: int,
                 maximum_quote_age_seconds: float, maximum_decision_age_seconds: float):
        self.broker, self.store, self.sessions = broker, store, sessions
        self.policy, self.magic = policy, magic
        if maximum_quote_age_seconds <= 0 or maximum_decision_age_seconds <= 0:
            raise ValueError("freshness limits must be positive")
        self.quote_age = maximum_quote_age_seconds
        self.decision_age = maximum_decision_age_seconds

    def execute(self, candidate: TradeCandidate, original_risk: RiskDecision,
                reviewed: ContextDecision, now: datetime,
                session_id: str, opening_balance: Decimal) -> ExecutionRecord:
        _require_utc(now, "now")
        if reviewed.plan is None:
            return ExecutionRecord("", "BLOCKED", None, "No actionable Layer 6 allowance.")
        original_plan = original_risk.permitted_position_plan
        if (original_plan is None or reviewed.risk_decision_id != original_risk.decision_id or
                original_risk.conviction.candidate_id != candidate.candidate_id or
                not enforce_layer6_ceiling(original_plan, reviewed.plan.volume,
                                           reviewed.plan.stop,
                                           reviewed.plan.requested_objective or
                                           reviewed.plan.minimum_objective, candidate.side) or
                reviewed.plan.actual_risk_amount > original_plan.actual_risk_amount):
            return ExecutionRecord("", "BLOCKED", None, "Review does not match its Layer 5 ceiling.")
        if not 0 <= (now - candidate.evaluation_time_utc).total_seconds() <= self.decision_age:
            return ExecutionRecord("", "BLOCKED", None, "Decision is stale or future-dated.")
        snapshot = self.broker.snapshot(candidate.symbol, now)
        client_id = "fx-" + hashlib.sha256(
            f"{snapshot.account.login}|{candidate.candidate_id}".encode()
        ).hexdigest()[:24]
        existing = self.store.get(client_id)
        if existing:
            return existing
        if self.store.unresolved():
            return ExecutionRecord(client_id, "BLOCKED", None,
                                   "Unreconciled submissions exist. Reconcile MT5 before entries.")
        age = (now - snapshot.tick.time_utc).total_seconds()
        if (not snapshot.connected or not snapshot.entries_allowed or
                not snapshot.tick.ask.is_finite() or not snapshot.tick.bid.is_finite() or
                not 0 < snapshot.tick.bid <= snapshot.tick.ask or
                not 0 <= age <= self.quote_age or snapshot.observed_at_utc != now):
            return ExecutionRecord(client_id, "BLOCKED", None,
                                   "Connection, market permission or quote freshness check failed.")
        if snapshot.account.mode is AccountMode.NETTING and any(
                p.symbol == snapshot.spec.broker_name for p in snapshot.positions):
            return ExecutionRecord(client_id, "BLOCKED", None,
                                   "Existing netting position requires explicit reconciliation.")
        daily = self.sessions.observe_equity(session_id, opening_balance,
                                             snapshot.account.equity, self.policy, now)
        entry = snapshot.tick.ask if candidate.side is Side.LONG else snapshot.tick.bid
        portfolio = PortfolioRiskState(tuple(p.risk_position() for p in snapshot.positions))
        # Without a requested objective, re-derive the minimum reward:risk target from the fresh
        # entry, as the original decision did. Reusing the old target would block every entry
        # whose price moved even one tick adversely during review, biasing results favourably.
        fresh = decide_risk(candidate, snapshot.account, snapshot.spec, entry,
                            reviewed.plan.stop, reviewed.plan.requested_objective,
                            portfolio, daily, self.policy)
        plan = fresh.permitted_position_plan
        if fresh.status is not DecisionStatus.ELIGIBLE or plan is None:
            reasons = ",".join(reason.value for reason in fresh.reasons) or "none"
            return ExecutionRecord(client_id, "BLOCKED", None,
                                   f"Fresh Layer 5 risk check blocked ({reasons}); flatten required="
                                   f"{fresh.flatten_required}.")
        # A changed price may increase loss per lot. Preserve both the old reviewed
        # money ceiling and the fresh Layer 5 ceiling, not just the number of lots.
        step = snapshot.spec.volume_step
        money_capped_volume = reviewed.plan.actual_risk_amount / plan.loss_per_lot
        volume = (min(plan.volume, reviewed.plan.volume, money_capped_volume) / step
                  ).to_integral_value(rounding=ROUND_FLOOR) * step
        if volume < snapshot.spec.volume_min:
            return ExecutionRecord(client_id, "BLOCKED", None, "Fresh size below broker minimum.")
        intent = OrderIntent(client_id, candidate.candidate_id, fresh.decision_id,
                             snapshot.account.login, snapshot.spec.broker_name, candidate.side,
                             volume, entry, plan.stop,
                             plan.requested_objective or plan.minimum_objective, self.magic, now)
        if not self.store.reserve(intent):
            record = self.store.get(client_id)
            return record or ExecutionRecord(client_id, "BLOCKED", None,
                                              "Another submission won the reservation; reconcile.")
        latest_halt = self.sessions.load(session_id, snapshot.account.equity)
        if latest_halt and evaluate_daily_risk(latest_halt, self.policy).new_entries_blocked:
            return self.store.update(client_id, "REJECTED", None,
                                     "Halt became active before submission; no order sent.", now)
        try:
            result = self.broker.submit(intent)
        except Exception as exc:  # noqa: BLE001 - any post-submit failure is an ambiguous broker result
            # Never resend after a transport failure: the broker may have accepted it.
            return self.store.update(client_id, "UNKNOWN", None,
                                     f"{type(exc).__name__}: outcome unknown; reconcile broker records.", now)
        return self.store.update(client_id, result.status, result.ticket, result.code, now)

    def reconcile(self, start: datetime, now: datetime) -> tuple[ExecutionRecord, ...]:
        """A missing record is not proof of non-execution; unresolved identities remain blocked."""
        evidence = self.broker.evidence(start, now)
        by_client: dict[str, list[BrokerEvidence]] = {}
        for item in evidence:
            by_client.setdefault(item.client_id, []).append(item)
        records = []
        for client_id in self.store.unresolved():
            found = by_client.get(client_id, [])
            if len({item.ticket for item in found if item.kind == "POSITION"}) > 1:
                records.append(self.store.update(client_id, "UNKNOWN", None,
                                                  "Multiple broker positions share one identity; review.", now))
            elif found:
                records.append(self.store.update(client_id, "RECONCILED", found[0].ticket,
                                                  "Broker evidence: " + ",".join(
                                                      sorted({e.kind for e in found})), now))
            else:
                records.append(self.store.update(client_id, "UNKNOWN", None,
                                                  "No conclusive broker evidence; do not retry.", now))
        return tuple(records)
