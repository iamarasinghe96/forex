"""Immutable local decision journal, reserve evidence and transactional cloud outbox."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from forex.domain import _require_utc
from forex.serialization import canonical_json


@dataclass(frozen=True)
class JournalEvent:
    sequence: int
    event_id: str
    mode: str
    kind: str
    entity_id: str
    observed_at_utc: datetime
    payload: Mapping[str, Any]
    payload_hash: str


def _event(row: tuple[Any, ...]) -> JournalEvent:
    return JournalEvent(int(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]),
                        datetime.fromisoformat(row[5]), json.loads(row[6]), str(row[7]))


def _empty_summary() -> dict[str, Any]:
    return {"event_count": 0, "kind_counts": {}, "closed_trades": 0, "wins": 0, "losses": 0,
            "realized_pnl_aud": "0", "reserve_aud": "0", "positive_pnl_aud": "0",
            "negative_pnl_aud": "0", "latest_balance": None, "latest_equity": None,
            "latest_health": None, "costs_complete": False}


class JournalStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS journal_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                    mode TEXT NOT NULL, kind TEXT NOT NULL, entity_id TEXT NOT NULL,
                    observed_at_utc TEXT NOT NULL, payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS journal_kind_time
                    ON journal_events(mode,kind,observed_at_utc);
                CREATE TABLE IF NOT EXISTS journal_outbox (
                    event_id TEXT PRIMARY KEY REFERENCES journal_events(event_id),
                    attempts INTEGER NOT NULL DEFAULT 0, next_attempt_utc TEXT NOT NULL,
                    last_error TEXT, synced_at_utc TEXT);
                CREATE TABLE IF NOT EXISTS journal_summaries (
                    mode TEXT NOT NULL, bucket TEXT NOT NULL, summary_json TEXT NOT NULL,
                    PRIMARY KEY(mode,bucket));
                CREATE TABLE IF NOT EXISTS tax_reserve_ledger (
                    event_id TEXT PRIMARY KEY, mode TEXT NOT NULL, closed_at_utc TEXT NOT NULL,
                    pnl_aud TEXT NOT NULL, rate_percent TEXT NOT NULL, reserve_aud TEXT NOT NULL,
                    pnl_basis TEXT NOT NULL);
            """)

    def append(self, mode: str, kind: str, entity_id: str, payload: Mapping[str, Any],
               observed_at_utc: datetime) -> JournalEvent:
        """Commit event, aggregate and outbox together; duplicate identities cannot change facts."""
        _require_utc(observed_at_utc, "observed_at_utc")
        if mode not in {"PAPER", "DEMO"} or not kind.isidentifier() or not entity_id:
            raise ValueError("journal requires PAPER/DEMO mode, named event kind and stable identity")
        value = dict(payload)
        if kind == "trade_closed":
            pnl, rate = Decimal(str(value["pnl_aud"])), Decimal(str(value["reserve_percent"]))
            if not pnl.is_finite() or not rate.is_finite() or not 0 <= rate <= 100:
                raise ValueError("trade P&L/rate must be finite and reserve rate inside 0..100")
            if value.get("pnl_basis") not in {"broker_reported", "simulated_incomplete_costs"}:
                raise ValueError("closed trade must disclose its P&L basis")
            value["reserve_aud"] = str(max(pnl, Decimal(0)) * rate / 100)
        serialized = canonical_json(value)
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        event_id = hashlib.sha256(f"{mode}|{kind}|{entity_id}".encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM journal_events WHERE event_id=?", (event_id,)).fetchone()
            if existing:
                if existing[7] != digest:
                    raise ValueError("journal identity conflict; original evidence cannot be overwritten")
                return _event(existing)
            db.execute("INSERT INTO journal_events VALUES (NULL,?,?,?,?,?,?,?)", (
                event_id, mode, kind, entity_id, observed_at_utc.isoformat(), serialized, digest,
            ))
            db.execute("INSERT INTO journal_outbox(event_id,next_attempt_utc) VALUES (?,?)",
                       (event_id, observed_at_utc.isoformat()))
            if kind == "trade_closed":
                db.execute("INSERT INTO tax_reserve_ledger VALUES (?,?,?,?,?,?,?)", (
                    event_id, mode, observed_at_utc.isoformat(), str(value["pnl_aud"]),
                    str(value["reserve_percent"]), value["reserve_aud"], value["pnl_basis"],
                ))
            for bucket in ("all", observed_at_utc.date().isoformat()):
                row = db.execute("SELECT summary_json FROM journal_summaries WHERE mode=? AND bucket=?",
                                 (mode, bucket)).fetchone()
                summary = json.loads(row[0]) if row else _empty_summary()
                summary["event_count"] += 1
                counts = summary["kind_counts"]
                counts[kind] = counts.get(kind, 0) + 1
                if kind == "trade_closed":
                    summary["closed_trades"] += 1
                    summary["wins"] += int(pnl > 0)
                    summary["losses"] += int(pnl < 0)
                    for name, amount in (("realized_pnl_aud", pnl),
                                         ("reserve_aud", Decimal(value["reserve_aud"])),
                                         ("positive_pnl_aud", max(pnl, Decimal(0))),
                                         ("negative_pnl_aud", max(-pnl, Decimal(0)))):
                        summary[name] = str(Decimal(summary[name]) + amount)
                    summary["costs_complete"] = (
                        (summary["closed_trades"] == 1 or summary["costs_complete"]) and
                        bool(value.get("costs_complete", False)))
                if kind == "balance" and observed_at_utc.isoformat() >= summary.get("balance_at_utc", ""):
                    summary["latest_balance"] = str(value["balance"])
                    summary["latest_equity"] = str(value["equity"])
                    summary["balance_at_utc"] = observed_at_utc.isoformat()
                if kind == "health" and observed_at_utc.isoformat() >= summary.get("health_at_utc", ""):
                    summary["latest_health"] = value
                    summary["health_at_utc"] = observed_at_utc.isoformat()
                summary["last_event_at_utc"] = max(summary.get("last_event_at_utc", ""),
                                                    observed_at_utc.isoformat())
                # Lets the dashboard ignore trades mirrored from an earlier paper account.
                summary["first_event_at_utc"] = min(summary.get("first_event_at_utc") or "9999",
                                                     observed_at_utc.isoformat())
                db.execute("INSERT INTO journal_summaries VALUES (?,?,?) ON CONFLICT(mode,bucket) "
                           "DO UPDATE SET summary_json=excluded.summary_json",
                           (mode, bucket, canonical_json(summary)))
            row = db.execute("SELECT * FROM journal_events WHERE event_id=?", (event_id,)).fetchone()
            assert row is not None
            return _event(row)

    def events(self, mode: str | None = None, *, after_sequence: int = 0,
               limit: int = 100) -> tuple[JournalEvent, ...]:
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT * FROM journal_events WHERE sequence>? "
                              "AND (? IS NULL OR mode=?) ORDER BY sequence LIMIT ?",
                              (after_sequence, mode, mode, limit)).fetchall()
        return tuple(_event(row) for row in rows)

    def pending(self, now: datetime, limit: int) -> tuple[JournalEvent, ...]:
        _require_utc(now, "now")
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT e.* FROM journal_events e JOIN journal_outbox o "
                              "ON e.event_id=o.event_id WHERE o.synced_at_utc IS NULL "
                              "AND o.next_attempt_utc<=? ORDER BY e.sequence LIMIT ?",
                              (now.isoformat(), limit)).fetchall()
        return tuple(_event(row) for row in rows)

    def acknowledge(self, event_id: str, now: datetime) -> None:
        _require_utc(now, "now")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE journal_outbox SET synced_at_utc=?,last_error=NULL WHERE event_id=?",
                       (now.isoformat(), event_id))

    def failed(self, event_id: str, now: datetime, error_type: str,
               base_delay_seconds: float, maximum_delay_seconds: float) -> None:
        _require_utc(now, "now")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT attempts FROM journal_outbox WHERE event_id=?", (event_id,)).fetchone()
            if row is None:
                raise ValueError("unknown outbox identity")
            attempts = int(row[0]) + 1
            delay = min(maximum_delay_seconds, base_delay_seconds * 2 ** min(attempts - 1, 20))
            db.execute("UPDATE journal_outbox SET attempts=?,next_attempt_utc=?,last_error=? "
                       "WHERE event_id=?", (attempts, (now + timedelta(seconds=delay)).isoformat(),
                                            error_type, event_id))

    def requeue(self, event_id: str, now: datetime) -> None:
        _require_utc(now, "now")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE journal_outbox SET synced_at_utc=NULL,next_attempt_utc=? "
                       "WHERE event_id=?", (now.isoformat(), event_id))

    def summary(self, mode: str, bucket: str = "all") -> dict[str, Any]:
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT summary_json FROM journal_summaries WHERE mode=? AND bucket=?",
                             (mode, bucket)).fetchone()
        return json.loads(row[0]) if row else _empty_summary()

    def export_csv(self, path: Path, mode: str) -> int:
        """Export complete audit payloads; spreadsheet formula prefixes are neutralized."""
        path.parent.mkdir(parents=True, exist_ok=True)
        count, after = 0, 0
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["event_id", "mode", "kind", "entity_id", "utc", "payload_json"])
            while events := self.events(mode, after_sequence=after, limit=1000):
                for event in events:
                    values = [event.event_id, event.mode, event.kind, event.entity_id,
                              event.observed_at_utc.isoformat(), canonical_json(event.payload)]
                    writer.writerow(["'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v
                                     for v in values])
                    count += 1
                    after = event.sequence
        return count
