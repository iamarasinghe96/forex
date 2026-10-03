"""Single-writer paper loop sharing analysis, risk, context and execution services."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
from typing import Any
from zoneinfo import ZoneInfo

from forex.alerts import TelegramAlerter
from forex.analysis import Side, analyse_market, atr, closed_candles
from forex.broker.base import Broker
from forex.cloud_sync import configured_worker
from forex.config import AppConfig, ExecutionConfig, Secrets
from forex.context import ContextReviewer
from forex.costs import CostRecorder
from forex.domain import Timeframe, _require_utc
from forex.errors import OperatorError
from forex.execution import ExecutionService, ExecutionStore
from forex.history import aggregate_h4
from forex.journal import JournalStore
from forex.learning import (
    LearningStore,
    apply_overlay,
    candidate_keys,
    describe_changes,
    overlay_path,
    read_overlay,
    scale_plan,
    sizing_decision,
    strategy_version,
)
from forex.market_data import validate_candle_freshness
from forex.notifications import NotificationWorker
from forex.paper import PaperBroker
from forex.persistence import CandleStore, RiskSessionStore
from forex.risk import DecisionStatus, PortfolioRiskState, evaluate_daily_risk
from forex.risk import decide_risk as evaluate_candidate
from forex.risk_policy import policy_from_config
from forex.scoring import ScoreModel, SetupFeatures, strategy_signature
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


def weekend_close_start(now: datetime) -> datetime | None:
    """Start of the weekly forex close (Fri 17:00 New York) if ``now`` falls inside it, else None."""
    ny = now.astimezone(ZoneInfo("America/New_York"))
    inside = ((ny.weekday() == 4 and ny.hour >= 17) or ny.weekday() == 5
              or (ny.weekday() == 6 and ny.hour < 17))
    if not inside:
        return None
    friday = (ny - timedelta(days=(ny.weekday() - 4) % 7)).replace(hour=17, minute=0, second=0, microsecond=0)
    return friday.astimezone(UTC)


class PaperRuntime:
    def __init__(self, config: AppConfig, feed: Broker, paper: PaperBroker,
                 reviewer: ContextReviewer, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        if config.mode != "paper" or not config.execution.rollover_configured:
            raise OperatorError("Paper runtime requires paper mode and an explicit daily-risk rollover hour.")
        self.config, self.feed, self.paper, self.reviewer, self.clock = config, feed, paper, reviewer, clock
        # config.yaml as loaded; operator-approved learning patches are layered on top of it.
        self.base_config = config
        self.overlay_path = overlay_path(paper.path)
        self.overlay_digest = ""
        self.learning = LearningStore(paper.path)
        self.policy = policy_from_config(config.risk)
        self.journal = JournalStore(paper.path)
        self.score_model: ScoreModel | None = None
        self.sessions = RiskSessionStore(paper.path)
        self.store = RuntimeStore(paper.path)
        self.candles = CandleStore(paper.path)
        self.costs = CostRecorder(paper.path)
        self.execution = ExecutionService(paper, ExecutionStore(paper.path), self.sessions,
                                          self.policy, config.broker.magic_number,
                                          config.execution.maximum_quote_age_seconds,
                                          config.execution.maximum_decision_age_seconds)
        self.started = clock()
        self.next_analysis = self.started
        self.entry_blocks: set[str] = set()
        # Latest H1 ATR per symbol for the optional paper trailing stop (paper.atr_trailing_multiple).
        self.trailing_atr: dict[str, Decimal] = {}
        self.atr_updated: dict[str, datetime] = {}  # Broker symbol -> when its ATR was last computed.
        # When each pair's quote went quiet (e.g. the daily rollover); entries pause meanwhile.
        self.stale_since: dict[str, datetime] = {}
        self.last_health_journal: tuple[datetime, str] | None = None
        # (error type, failing since, last reported or None, consecutive failed cycles)
        self.failure: tuple[str, datetime, datetime | None, int] | None = None
        self.config_fingerprint = hashlib.sha256(config.model_dump_json().encode()).hexdigest()
        source = hashlib.sha256()
        for path in sorted(Path(__file__).parent.rglob("*.py")):
            source.update(str(path.relative_to(Path(__file__).parent)).encode())
            source.update(path.read_bytes())
        self.code_fingerprint = source.hexdigest()
        self.reload_strategy(self.started, announce=False)

    def refresh_position_atr(self, now: datetime) -> None:
        """Keep the trailing-stop ATR current for every held pair: after a restart, and when the
        pair's hourly analysis is skipped (paused pair or quiet quote). Same 14-bar H1 ATR."""
        held = {p.symbol for p in self.paper.positions()}
        period = self.config.analysis.atr_period
        for symbol in self.config.broker.symbols:
            broker_symbol = self.feed.resolve_symbol(symbol).broker_name
            updated = self.atr_updated.get(broker_symbol)
            if broker_symbol not in held or (updated is not None and now - updated < timedelta(hours=1)):
                continue
            try:
                recent = closed_candles(self.feed.candles(symbol, Timeframe.H1, now - timedelta(days=7), now), now)
                self.trailing_atr[broker_symbol] = Decimal(str(atr(recent, period)))
                self.atr_updated[broker_symbol] = now
            except Exception as exc:  # noqa: BLE001 - keep the previous ATR; retry next cycle
                logging.getLogger("forex.paper").warning("ATR refresh for %s failed (%s); previous value kept.",
                                                         symbol, type(exc).__name__)

    def reload_strategy(self, now: datetime, *, announce: bool = True) -> None:
        """Load the approved strategy overlay when it changes; an invalid file keeps current settings."""
        try:
            raw = self.overlay_path.read_bytes() if self.overlay_path.exists() else b""
        except OSError:
            return
        digest = hashlib.sha256(raw).hexdigest()
        if digest == self.overlay_digest:
            return
        self.overlay_digest = digest
        try:
            effective = apply_overlay(self.base_config, read_overlay(self.overlay_path))
        except (ValueError, OSError):
            self.emit("alert", "overlay:" + digest[:16], {"reason": "Approved strategy settings file is invalid; "
                      "previous settings kept. Send /rollback in Telegram."}, now)
            return
        changes = describe_changes(self.config, effective)
        self.config = effective
        self.load_score_model(now)
        self.policy = policy_from_config(effective.risk)
        self.execution = ExecutionService(self.paper, ExecutionStore(self.paper.path), self.sessions,
                                          self.policy, effective.broker.magic_number,
                                          effective.execution.maximum_quote_age_seconds,
                                          effective.execution.maximum_decision_age_seconds)
        self.config_fingerprint = hashlib.sha256(effective.model_dump_json().encode()).hexdigest()
        if changes:
            logging.getLogger("forex.paper").info("Strategy settings loaded: %s", "; ".join(changes))
            if announce:
                version = strategy_version(effective)
                self.emit("strategy_updated", digest[:16] + "|" + now.isoformat(),
                          {"changes": changes, "strategy_version": version,
                           "message": f"Strategy updated and running (settings {version}; scores restart "
                                      "for these settings): " + "; ".join(changes)}, now)

    def load_score_model(self, now: datetime) -> None:
        """Load once per configuration reload; activation fails closed on missing evidence."""
        scoring = self.config.scoring
        self.score_model = None
        if not (scoring.enabled or scoring.shadow):
            return
        try:
            model = ScoreModel.load(scoring.model_path)
            if model.document.get("strategy_signature") != strategy_signature(self.config):
                raise ValueError("setup model analysis or exit rules differ from runtime")
            if scoring.enabled and not scoring.shadow:
                model.require_acceptance(self.config)
                with closing(sqlite3.connect(self.journal.path)) as db:
                    row = db.execute(
                        "SELECT MIN(observed_at_utc),MAX(observed_at_utc) FROM journal_events "
                        "WHERE mode='PAPER' AND kind='candidate' "
                        "AND json_extract(payload_json,'$.setup_score.model_sha256')=? "
                        "AND json_extract(payload_json,'$.setup_score.shadow')=1 "
                        "AND json_extract(payload_json,'$.setup_score.status')='available' "
                        "AND json_extract(payload_json,'$.setup_score.strategy_signature')=?",
                        (model.sha256, strategy_signature(self.config)),
                    ).fetchone()
                if not row or not row[0] or not row[1] or datetime.fromisoformat(row[1]) > now or (
                    datetime.fromisoformat(row[1]) - datetime.fromisoformat(row[0]) < timedelta(weeks=4)
                ):
                    raise ValueError("setup sizing requires at least four weeks of recorded shadow scores for this model")
            self.score_model = model
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if scoring.enabled and not scoring.shadow:
                raise OperatorError(f"Setup sizing blocked: {exc}") from exc
            logging.getLogger("forex.paper").warning("Setup shadow model unavailable (%s)", type(exc).__name__)

    def record_costs(self, snaps: dict[str, Any], now: datetime) -> None:
        """Sample live spreads and swap rates for scripts/cost_report.py; never interrupts trading."""
        try:
            for symbol, snap in snaps.items():
                if (now - snap.tick.time_utc).total_seconds() <= self.paper.quote_age:
                    self.costs.observe(symbol, snap.spec.broker_name, snap.tick, snap.spec.pip_size, now)
            self.costs.flush(now, self.feed.swap_rates)
        except Exception as exc:  # noqa: BLE001 - cost observation is research only
            logging.getLogger("forex.paper").warning("Cost sampling failed (%s); trading continues.",
                                                     type(exc).__name__)

    def track_stale_quotes(self, now: datetime) -> set[str]:
        stale = {symbol for symbol in self.config.broker.symbols if not self.paper.quote_fresh(symbol, now)}
        for symbol in set(self.stale_since) - stale:
            del self.stale_since[symbol]
        for symbol in sorted(stale):
            since = self.stale_since.setdefault(symbol, now)
            if since == now:
                logging.getLogger("forex.paper").info("%s quote paused (quiet market or rollover); entries wait for fresh prices", symbol)
            minutes = (now - since).total_seconds() / 60
            closed_from = weekend_close_start(now)
            if closed_from is not None:
                # Weekly close (Fri 17:00 to Sun 17:00 New York): one notice per weekend, no errors.
                self.emit("alert", "weekend-close:" + closed_from.date().isoformat(),
                          {"reason": "Market closed for the weekend; the bot is idle until it reopens "
                           "Sunday 17:00 New York time (Monday morning in Sydney). No action needed."}, now)
                continue
            if minutes * 60 > self.config.paper.stale_quote_alert_seconds:
                raise OperatorError(f"No fresh {symbol} quote for {minutes:.0f} min. Normal while the "
                                    "market is closed; otherwise check MT5 is connected.")
        return stale

    def session_id(self, now: datetime) -> str:
        return paper_session_id(now, self.config.execution)

    def emit(self, kind: str, identity: str, payload: dict[str, Any], now: datetime) -> None:
        self.journal.append("PAPER", kind, identity, payload, now)

    def cycle(self) -> None:
        now = self.clock()
        self.reload_strategy(now)
        live_account = self.feed.account_state()
        if live_account.login != self.paper.account.login or live_account.currency != "AUD":
            raise OperatorError("Market-data account identity changed. Halt paper and inspect MT5.")
        # Check feed freshness even when flat or between hourly analysis passes. A pair that has
        # not ticked recently only pauses its own entries; a long silence is reported as an error.
        stale = self.track_stale_quotes(now)
        snaps = {symbol: self.paper.snapshot(symbol, now) for symbol in self.config.broker.symbols
                 if symbol not in stale}
        blocked = {symbol for symbol, snap in snaps.items() if not snap.entries_allowed}
        self.record_costs(snaps, now)
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
        trail = self.config.paper.atr_trailing_multiple
        if trail is not None and not self.config.paper.halt_file.exists():  # A halt only flattens.
            self.refresh_position_atr(now)
        self.paper.manage(now, atr_by_symbol=self.trailing_atr,
                          atr_multiple=Decimal(str(trail)) if trail is not None else None)
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
            if symbol in stale:
                logging.getLogger("forex.paper").info("%s quote is quiet; skipping this hour's evaluation for it", symbol)
                continue
            if symbol.upper() in {p.upper() for p in self.config.learning.disabled_pairs}:
                continue  # Paused by an approved learning review; open trades are still managed.
            recent = closed_candles(self.feed.candles(symbol, Timeframe.H1,
                                    now - timedelta(days=self.config.paper.history_days), now), now)
            if not recent:
                raise OperatorError("Closed paper market history is unavailable; restore MT5 data.")
            validate_candle_freshness(recent[-1], now, self.config.market_data)
            self.candles.upsert(recent)
            h1 = list(self.candles.load(symbol, Timeframe.H1))
            # H4 bars come from H1 on fixed UTC boundaries, as in the research data, not from MT5
            # (whose H4 bars start at the broker's midnight, 1-2 hours off the tested bars).
            h4 = aggregate_h4(h1, self.config.market_data.h4_alignment_hour_utc)
            result = analyse_market(symbol, h1, h4, now, self.config.analysis)
            broker_symbol = self.feed.resolve_symbol(symbol).broker_name
            self.trailing_atr[broker_symbol] = Decimal(str(result.snapshot.feature_snapshot["h1_atr"]))
            self.atr_updated[broker_symbol] = now
            identity = result.snapshot.evaluation_id
            if not self.store.claim(identity, now):
                continue
            payload = {"symbol": symbol, "timeframe": "H1", "analysis": json_value(result.snapshot),
                       "strategy_version": strategy_version(self.config, self.score_model.sha256 if self.score_model else "")}
            dynamic_scoring = self.config.scoring.enabled and not self.config.scoring.shadow
            payload["sizing_version"] = (payload["strategy_version"] if dynamic_scoring else
                                         strategy_version(self.config, ""))
            candidate = result.candidate
            if candidate is None:
                self.emit("no_trade", identity, {**payload, "reason": result.snapshot.no_candidate_reason}, now)
                self.store.complete(identity, now)
                continue
            setup_score = None
            score_payload: dict[str, Any] = {"status": "disabled", "shadow": True}
            if self.config.scoring.enabled or self.config.scoring.shadow:
                try:
                    features = SetupFeatures.from_snapshot(result.snapshot)
                    score_payload = {"status": "unavailable", "shadow": True, "features": dict(features.values),
                                     "strategy_signature": strategy_signature(self.config)}
                    if self.score_model is not None:
                        setup_score = self.score_model.score(features)
                        score_payload.update(json_value(setup_score), status="available",
                                             shadow=not dynamic_scoring)
                except (ValueError, KeyError, ZeroDivisionError) as exc:
                    if dynamic_scoring:
                        raise  # Live sizing fails closed: no score, no trade.
                    # Shadow scoring is observation only and must never stop a trade.
                    setup_score = None
                    score_payload = {"status": "error", "shadow": True, "error": type(exc).__name__}
            payload.update(candidate=json_value(candidate), trade_style=candidate.trade_style.value,
                           setup_score=score_payload)
            self.emit("candidate", identity, payload, now)
            snap = self.paper.snapshot(symbol, self.clock())
            if not snap.entries_allowed:
                self.emit("hard_risk_block", identity, {**payload, "reason": "Broker market entry permission blocked"}, self.clock())
                self.store.complete(identity, self.clock())
                continue
            holding = sum(1 for p in snap.positions if p.symbol.upper().split(".")[0] == symbol.upper())
            if holding >= self.config.paper.max_positions_per_pair:
                # Backtests take one trade per pair at a time; hourly re-entries would stack risk.
                self.emit("no_trade", identity, {**payload, "reason": f"Already holding {holding} {symbol} "
                          "position(s) (paper.max_positions_per_pair)"}, self.clock())
                self.store.complete(identity, self.clock())
                continue
            entry = snap.tick.ask if candidate.side is Side.LONG else snap.tick.bid
            stop = Decimal(str(candidate.structural_reference_levels[
                "rolling_low" if candidate.side is Side.LONG else "rolling_high"]))
            fresh_now = self.clock()
            daily = self.sessions.observe_equity(day, snap.account.balance, snap.account.equity,
                                                 self.policy, fresh_now)
            target_rr = self.config.paper.target_reward_risk
            objective = (None if target_rr is None else
                         entry + (entry - stop) * Decimal(str(target_rr)))
            risk = evaluate_candidate(candidate, snap.account, snap.spec, entry, stop, objective,
                                      PortfolioRiskState(tuple(p.risk_position() for p in snap.positions)),
                                      daily, self.policy, setup_score=setup_score, scoring=self.config.scoring)
            self.emit("risk_decision", identity, {**payload, "risk": json_value(risk)}, fresh_now)
            if risk.status is not DecisionStatus.ELIGIBLE:
                self.emit("hard_risk_block", identity, {**payload, "risk": json_value(risk)}, fresh_now)
                self.store.complete(identity, fresh_now)
                continue
            reviewed = self.reviewer.review(risk, snap.spec, payload,
                                            {identity: canonical_json(payload)}, fresh_now)
            learning = self.config.learning
            if reviewed.plan is not None and learning.enabled and learning.apply_to_sizing:
                sizing = sizing_decision(self.learning.scores(learning.prior_trades, payload["sizing_version"],
                                                             sizing=not dynamic_scoring),
                                         candidate_keys(symbol, {**json_value(candidate),
                                                                 "setup_score": score_payload if dynamic_scoring else {}}),
                                         min_trades=learning.min_trades, min_factor=learning.min_factor,
                                         skip_below_r=learning.skip_below_r, evidence_z=learning.evidence_z)
                self.emit("learning_decision", identity, {"symbol": symbol, "sizing": json_value(sizing)}, fresh_now)
                reviewed = (replace(reviewed, plan=None, status="LEARNING_SKIPPED", rationale=sizing.reason)
                            if sizing.skip else scale_plan(reviewed, sizing.factor, snap.spec))
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
                spread = snap.tick.ask - snap.tick.bid
                self.emit("execution", identity, {**payload, "record": json_value(record),
                          "entry_spread_pips": float(spread / snap.spec.pip_size),
                          "entry_spread_r": float(spread / abs(entry - stop)) if entry != stop else None}, execution_now)
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
            # A visible sign of life in the console, once per journaled heartbeat (not every cycle).
            logging.getLogger("forex.paper").info(
                "%s | balance AUD %s | equity AUD %s | open trades %s", status.capitalize(),
                account.balance.quantize(Decimal("0.01")), account.equity.quantize(Decimal("0.01")),
                len(payload["positions"]))
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
        helpers: list[Thread] = []
        if self.config.telegram.enabled:
            secrets = Secrets()
            if not secrets.telegram_bot_token or not secrets.telegram_chat_id:
                raise OperatorError("Telegram is enabled without local credentials; configure or disable it.")
            notifier = NotificationWorker(self.journal, TelegramAlerter(
                secrets.telegram_bot_token, secrets.telegram_chat_id,
                self.config.telegram.timeout_seconds, "PAPER"))
            alert_thread = Thread(target=notifier.run, args=(stop,), daemon=True)
            if self.config.learning.enabled and self.config.learning.telegram_commands:
                from forex.telegram_commands import CommandHandler, TelegramCommandWorker
                handler = CommandHandler(self.base_config, self.learning, self.overlay_path, self.clock)
                commands = TelegramCommandWorker(handler, secrets.telegram_bot_token, secrets.telegram_chat_id,
                                                 self.learning)
                helpers.append(Thread(target=commands.run, args=(stop,), daemon=True))
        if self.config.learning.enabled:
            from forex.learning_worker import LearningWorker
            learner = LearningWorker(lambda: self.config, self.journal, self.learning,
                                     getattr(self.reviewer, "provider", None),
                                     lambda symbol: self.candles.load(symbol, Timeframe.H1), self.clock)
            helpers.append(Thread(target=learner.run, args=(stop,), daemon=True))
        if thread:
            thread.start()
        if alert_thread:
            alert_thread.start()
        for helper in helpers:
            helper.start()
        cycles = 0
        try:
            while not stop.is_set() and (maximum_cycles is None or cycles < maximum_cycles):
                try:
                    self.cycle()
                except Exception as exc:  # noqa: BLE001 - persist failure and stop entries until next healthy cycle
                    # OperatorError messages are written by this project and contain no secrets.
                    detail = str(exc)[:300] if isinstance(exc, OperatorError) else None
                    self.record_failure(type(exc).__name__, self.clock(), detail)
                else:
                    if self.failure is not None:
                        now = self.clock()
                        kind, since, reported, count = self.failure
                        message = f"Recovered after {count} failed cycles ({kind}) since {since.isoformat()}"
                        logging.getLogger("forex.paper").info("%s", message)
                        if reported is not None:
                            self.emit("alert", "recovered:" + now.isoformat(), {"reason": message}, now)
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


    def record_failure(self, error_type: str, now: datetime, detail: str | None = None) -> None:
        """Every failed cycle is logged locally. The journal (Telegram/cloud) gets a failure only
        once it has persisted for error_grace_seconds, then one reminder per error_repeat_seconds."""
        logging.getLogger("forex.paper").error("Paper cycle failed: %s%s; entries halted.", error_type,
                                               f" ({detail})" if detail else "")
        previous = self.failure
        if previous is None or previous[0] != error_type:
            self.failure = (error_type, now, None, 1)
        else:
            self.failure = (error_type, previous[1], previous[2], previous[3] + 1)
        _, since, reported, count = self.failure
        paper = self.config.paper
        due = ((now - since).total_seconds() >= paper.error_grace_seconds if reported is None
               else (now - reported).total_seconds() >= paper.error_repeat_seconds)
        if not due:
            return
        self.failure = (error_type, since, now, count)
        self.emit("error", now.isoformat(), {
            "error_type": error_type, "reason": detail or error_type, "consecutive_failed_cycles": count,
            "failing_since_utc": since,
            "action": "Entries halted while this persists; inspect local logs and market data"}, now)


def read_heartbeat(path: Path, now: datetime, maximum_age_seconds: float) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = (now - datetime.fromisoformat(data["observed_at_utc"])).total_seconds()
        return 0 <= age <= maximum_age_seconds and data["mode"] == "PAPER"
    except (OSError, ValueError, KeyError, TypeError):
        return False
