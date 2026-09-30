"""Single-writer paper loop sharing analysis, risk, context and execution services."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
from typing import Any
from zoneinfo import ZoneInfo

from forex.alerts import TelegramAlerter
from forex.analysis import Side, analyse_market, closed_candles
from forex.broker.base import Broker
from forex.cloud_sync import configured_worker
from forex.config import AppConfig, ExecutionConfig, Secrets
from forex.context import ContextReviewer
from forex.domain import Timeframe, _require_utc
from forex.errors import OperatorError
from forex.execution import ExecutionService, ExecutionStore
from forex.journal import JournalStore
from forex.market_data import validate_candle_freshness
from forex.notifications import NotificationWorker
from forex.paper import PaperBroker
from forex.persistence import CandleStore, RiskSessionStore
from forex.risk import DecisionStatus, PortfolioRiskState, evaluate_daily_risk
from forex.risk import decide_risk as evaluate_candidate
from forex.risk_policy import policy_from_config
from forex.serialization import canonical_json, json_value


def paper_session_id(now: datetime, config: ExecutionConfig) -> str:
    """Label the risk day by its opening date; NY close follows US DST rules."""
    _require_utc(now, "risk session timestamp")
    if config.session_rollover is not None:
        if config.session_rollover_hour_utc is not None:
            raise OperatorError("Conflicting daily-risk boundaries; choose exactly one.")
        local = now.astimezone(ZoneInfo("America/New_York"))
        day = local.date() if local.hour >= 17 else local.date() - timedelta(days=1)
        return "PAPER:NY17:" + day.isoformat()
    hour = config.session_rollover_hour_utc
    if hour is None:
        raise OperatorError("Configure a daily-risk session boundary before paper operation.")
    # Preserve existing fixed-UTC identities for previously configured databases.
    return "PAPER:" + (now - timedelta(hours=hour)).date().isoformat()


class RuntimeStore:
    def __init__(self, path: Path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS runtime_evaluations (identity TEXT PRIMARY KEY, claimed_at TEXT NOT NULL, completed_at TEXT)")

    def claim(self, identity: str, now: datetime) -> bool:
        # At most one attempt per closed-bar identity. A crash retains incomplete evidence,
        # never quietly repeats a paid review or sends another order.
        with closing(sqlite3.connect(self.path)) as db, db:
            return db.execute("INSERT OR IGNORE INTO runtime_evaluations VALUES (?,?,NULL)",
                              (identity, now.isoformat())).rowcount == 1

    def complete(self, identity: str, now: datetime) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE runtime_evaluations SET completed_at=? WHERE identity=?",
                       (now.isoformat(), identity))


class PaperRuntime:
    def __init__(self, config: AppConfig, feed: Broker, paper: PaperBroker,
                 reviewer: ContextReviewer, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        if config.mode != "paper" or not config.execution.rollover_configured:
            raise OperatorError("Paper runtime requires paper mode and an explicit daily-risk rollover hour.")
        self.config, self.feed, self.paper, self.reviewer, self.clock = config, feed, paper, reviewer, clock
        self.policy = policy_from_config(config.risk)
        self.journal = JournalStore(paper.path)
        self.sessions = RiskSessionStore(paper.path)
        self.store = RuntimeStore(paper.path)
        self.candles = CandleStore(paper.path)
        self.execution = ExecutionService(paper, ExecutionStore(paper.path), self.sessions,
                                          self.policy, config.broker.magic_number,
                                          config.execution.maximum_quote_age_seconds,
                                          config.execution.maximum_decision_age_seconds)
        self.started = clock()
        self.next_analysis = self.started
        self.entry_blocks: set[str] = set()
        self.last_health_journal: tuple[datetime, str] | None = None
        # (error type, failing since, last reported, consecutive failed cycles)
        self.failure: tuple[str, datetime, datetime, int] | None = None
        self.config_fingerprint = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
        source = hashlib.sha256()
        for path in sorted(Path(__file__).parent.rglob("*.py")):
            source.update(str(path.relative_to(Path(__file__).parent)).encode())
            source.update(path.read_bytes())
        self.code_fingerprint = source.hexdigest()

    def session_id(self, now: datetime) -> str:
        return paper_session_id(now, self.config.execution)

    def emit(self, kind: str, identity: str, payload: dict[str, Any], now: datetime) -> None:
        self.journal.append("PAPER", kind, identity, payload, now)

    def cycle(self) -> None:
        now = self.clock()
        live_account = self.feed.account_state()
        if live_account.login != self.paper.account.login or live_account.currency != "AUD":
            raise OperatorError("Market-data account identity changed. Halt paper and inspect MT5.")
        # Check feed freshness even when flat or between hourly analysis passes.
        blocked = {symbol for symbol in self.config.broker.symbols
                   if not self.paper.snapshot(symbol, now).entries_allowed}
        for symbol in blocked - self.entry_blocks:
            self.emit("alert", "market:" + symbol + now.isoformat(),
                      {"symbol": symbol, "reason": "Market entry permission blocked (close-only, disabled or restricted mode)"}, now)
        self.entry_blocks = blocked
        self.execution.reconcile(datetime(2000, 1, 1, tzinfo=UTC), now)
        # Observe pre-exit equity first so a loss cannot disappear from the circuit
        # comparison when realizing it into a newly lower balance.
        before = self.paper.state(now)
        self.sessions.observe_equity(self.session_id(now), before.balance, before.equity,
                                     self.policy, now)
        self.paper.manage(now)
        self.paper.journal_fills(self.journal)
        account = self.paper.state(now)
        day = self.session_id(now)
        daily = self.sessions.observe_equity(day, account.balance, account.equity, self.policy, now)
        if self.config.paper.halt_file.exists() or evaluate_daily_risk(daily, self.policy).new_entries_blocked:
            self.paper.manage(now, flatten=True)
            self.paper.journal_fills(self.journal)
            self.emit("alert", "halt:" + now.isoformat(), {"reason": "Paper halt or daily loss circuit; flatten simulated positions", "session": day}, now)
            self.heartbeat(now, "HALTED")
            return
        if now < self.next_analysis:
            self.heartbeat(now, "RUNNING")
            return
        for symbol in self.config.broker.symbols:
            bars = {}
            for timeframe in Timeframe:
                recent = closed_candles(self.feed.candles(symbol, timeframe,
                                        now - timedelta(days=self.config.paper.history_days), now), now)
                if not recent:
                    raise OperatorError("Closed paper market history is unavailable; restore MT5 data.")
                validate_candle_freshness(recent[-1], now, self.config.market_data)
                self.candles.upsert(recent)
                bars[timeframe] = self.candles.load(symbol, timeframe)
            result = analyse_market(symbol, bars[Timeframe.H1], bars[Timeframe.H4], now, self.config.analysis)
            identity = result.snapshot.evaluation_id
            if not self.store.claim(identity, now):
                continue
            payload = {"symbol": symbol, "timeframe": "H1", "analysis": json_value(result.snapshot)}
            candidate = result.candidate
            if candidate is None:
                self.emit("no_trade", identity, {**payload, "reason": result.snapshot.no_candidate_reason}, now)
                self.store.complete(identity, now)
                continue
            payload.update(candidate=json_value(candidate), trade_style=candidate.trade_style.value)
            self.emit("candidate", identity, payload, now)
            snap = self.paper.snapshot(symbol, self.clock())
            if not snap.entries_allowed:
                self.emit("hard_risk_block", identity, {**payload, "reason": "Broker market entry permission blocked"}, self.clock())
                self.store.complete(identity, self.clock())
                continue
            entry = snap.tick.ask if candidate.side is Side.LONG else snap.tick.bid
            stop = Decimal(str(candidate.structural_reference_levels[
                "rolling_low" if candidate.side is Side.LONG else "rolling_high"]))
            fresh_now = self.clock()
            daily = self.sessions.observe_equity(day, snap.account.balance, snap.account.equity,
                                                 self.policy, fresh_now)
            risk = evaluate_candidate(candidate, snap.account, snap.spec, entry, stop, None,
                                      PortfolioRiskState(tuple(p.risk_position() for p in snap.positions)),
                                      daily, self.policy)
            self.emit("risk_decision", identity, {**payload, "risk": json_value(risk)}, fresh_now)
            if risk.status is not DecisionStatus.ELIGIBLE:
                self.emit("hard_risk_block", identity, {**payload, "risk": json_value(risk)}, fresh_now)
                self.store.complete(identity, fresh_now)
                continue
            reviewed = self.reviewer.review(risk, snap.spec, payload,
                                            {identity: canonical_json(payload)}, fresh_now)
            self.emit("context_review", identity, {**payload, "review": json_value(reviewed)}, self.clock())
            if reviewed.alert_required:
                self.emit("alert", "context:" + identity, {"reason": "All context providers unavailable"}, self.clock())
            if reviewed.plan is None:
                self.emit("context_rejection", identity, {**payload, "review": json_value(reviewed)}, self.clock())
            elif self.config.paper.halt_file.exists():
                self.emit("hard_risk_block", "halt:" + identity, {"reason": "Paper halt arrived during context review", **payload}, self.clock())
            else:
                execution_now = self.clock()
                record = self.execution.execute(candidate, risk, reviewed, execution_now,
                                                self.session_id(execution_now), snap.account.balance)
                self.emit("execution", identity, {**payload, "record": json_value(record)}, execution_now)
            self.store.complete(identity, self.clock())
        self.paper.journal_fills(self.journal)
        self.periodic_evidence(self.clock())
        self.heartbeat(self.clock(), "RUNNING")
        self.next_analysis = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    def periodic_evidence(self, now: datetime) -> None:
        with closing(sqlite3.connect(self.paper.path)) as db, db:
            calls = db.execute("SELECT id,input_hash,provider,model,status,input_tokens,output_tokens,reported_cost_usd,created_at_utc FROM context_calls").fetchall()
        for row in calls:
            self.emit("context_call", str(row[0]), dict(zip(
                ("input_hash", "provider", "model", "status", "input_tokens", "output_tokens", "cost_usd"),
                row[1:8], strict=True)), datetime.fromisoformat(row[8]))
        yesterday = (now - timedelta(days=1)).date().isoformat()
        if self.store.claim("summary:" + yesterday, now):
            self.emit("daily_summary", yesterday, self.journal.summary("PAPER", yesterday), now)
        with closing(sqlite3.connect(self.paper.path)) as db, db:
            row = db.execute("SELECT MAX(opened_at) FROM paper_positions").fetchone()
        last = datetime.fromisoformat(row[0]) if row[0] else self.started
        if (now - last).total_seconds() >= self.config.paper.no_trade_hours * 3600:
            identity = "silence:" + now.date().isoformat()
            if self.store.claim(identity, now):
                self.emit("alert", identity, {"reason": "No paper fills beyond configured window",
                          "last_fill_or_start_utc": last, "hours": self.config.paper.no_trade_hours}, now)

    def heartbeat(self, now: datetime, status: str) -> None:
        account = self.paper.state(now)
        identity = now.isoformat()
        payload = {"status": status, "connection": "MARKET_DATA_OBSERVED", "positions": json_value(self.paper.position_status(now)),
                   "started_at_utc": self.started, "observed_at_utc": now, "mode": "PAPER",
                   "config_fingerprint": self.config_fingerprint, "code_fingerprint": self.code_fingerprint}
        payload["entry_blocked_symbols"] = sorted(self.entry_blocks)
        last = self.last_health_journal
        if (last is None or last[1] != status or
                (now - last[0]).total_seconds() >= self.config.paper.health_journal_seconds):
            # Every journal event is mirrored to the cloud, so a 5-second cadence would cost
            # tens of thousands of writes a day; status changes are still recorded at once.
            self.emit("balance", identity, {"balance": account.balance, "equity": account.equity}, now)
            self.emit("health", identity, payload, now)
            self.last_health_journal = (now, status)
        path = self.config.paper.heartbeat_file
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(canonical_json(payload), encoding="utf-8")
        temporary.replace(path)

    def run(self, stop: Event, maximum_cycles: int | None = None) -> None:
        worker = configured_worker(self.config.cloud, self.journal, self.config.paper.halt_file)
        thread = Thread(target=worker.run, args=(stop, self.clock, self.config.cloud.poll_seconds,
                                                self.config.cloud.batch_size), daemon=True) if worker else None
        alert_thread = None
        if self.config.telegram.enabled:
            secrets = Secrets()
            if not secrets.telegram_bot_token or not secrets.telegram_chat_id:
                raise OperatorError("Telegram is enabled without local credentials; configure or disable it.")
            notifier = NotificationWorker(self.journal, TelegramAlerter(
                secrets.telegram_bot_token, secrets.telegram_chat_id,
                self.config.telegram.timeout_seconds, "PAPER"))
            alert_thread = Thread(target=notifier.run, args=(stop,), daemon=True)
        if thread:
            thread.start()
        if alert_thread:
            alert_thread.start()
        cycles = 0
        try:
            while not stop.is_set() and (maximum_cycles is None or cycles < maximum_cycles):
                try:
                    self.cycle()
                except Exception as exc:  # noqa: BLE001 - persist failure and stop entries until next healthy cycle
                    self.record_failure(type(exc).__name__, self.clock())
                else:
                    if self.failure is not None:
                        now = self.clock()
                        kind, since, _, count = self.failure
                        self.emit("alert", "recovered:" + now.isoformat(), {
                            "reason": f"Recovered after {count} failed cycles ({kind}) since {since.isoformat()}"}, now)
                        self.failure = None
                cycles += 1
                if maximum_cycles is None or cycles < maximum_cycles:
                    stop.wait(self.config.paper.poll_seconds)
        finally:
            stop.set()
            if thread:
                thread.join(timeout=5)
            if alert_thread:
                alert_thread.join(timeout=5)
            self.feed.disconnect()


    def record_failure(self, error_type: str, now: datetime) -> None:
        """Every failed cycle is logged locally; the journal (Telegram/cloud) gets the first
        failure of a streak and then one reminder per error_repeat_seconds, not one per cycle."""
        logging.getLogger("forex.paper").error("Paper cycle failed: %s; entries halted.", error_type)
        previous = self.failure
        if previous is None or previous[0] != error_type:
            self.failure = (error_type, now, now, 1)
        else:
            due = (now - previous[2]).total_seconds() >= self.config.paper.error_repeat_seconds
            self.failure = (error_type, previous[1], now if due else previous[2], previous[3] + 1)
            if not due:
                return
        _, since, _, count = self.failure
        self.emit("error", now.isoformat(), {
            "error_type": error_type, "consecutive_failed_cycles": count, "failing_since_utc": since,
            "action": "Entries halted while this persists; inspect local logs and market data"}, now)


def read_heartbeat(path: Path, now: datetime, maximum_age_seconds: float) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = (now - datetime.fromisoformat(data["observed_at_utc"])).total_seconds()
        return 0 <= age <= maximum_age_seconds and data["mode"] == "PAPER"
    except (OSError, ValueError, KeyError, TypeError):
        return False
