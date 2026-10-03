"""Independent phone-alert delivery from durable journal evidence."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from threading import Event

from forex.alerts import TelegramAlerter
from forex.journal import JournalStore


class NotificationWorker:
    def __init__(self, journal: JournalStore, alerter: TelegramAlerter):
        self.journal, self.alerter = journal, alerter
        with closing(sqlite3.connect(journal.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS notification_cursor (id INTEGER PRIMARY KEY CHECK(id=1), sequence INTEGER NOT NULL)")
            db.execute("INSERT OR IGNORE INTO notification_cursor VALUES (1,0)")

    def once(self) -> int:
        with closing(sqlite3.connect(self.journal.path)) as db, db:
            cursor = db.execute("SELECT sequence FROM notification_cursor WHERE id=1").fetchone()[0]
        count = 0
        for event in self.journal.events("PAPER", after_sequence=cursor, limit=100):
            if event.kind == "daily_summary":
                p = event.payload
                self.alerter.send(f"Daily summary {event.entity_id}: {p.get('closed_trades', 0)} trades closed "
                                  f"({p.get('wins', 0)} won, {p.get('losses', 0)} lost), "
                                  f"P&L A${float(p.get('realized_pnl_aud', 0)):+.2f}.")
                count += 1
            elif event.kind in {"trade_review", "strategy_updated"}:
                # Learning messages are composed by the bot from its own records (no account details).
                self.alerter.send(str(event.payload.get("message", event.kind))[:3500])
                count += 1
            elif event.kind in {"trade_opened", "trade_closed", "alert", "error"}:
                score = ((event.payload.get("decision_provenance") or {}).get("candidate", {}).get("setup_score", {})
                         if isinstance(event.payload.get("decision_provenance"), dict) else {})
                risk = ((event.payload.get("decision_provenance") or {}).get("context_review", {}).get("review", {}).get("plan", {})
                        if isinstance(event.payload.get("decision_provenance"), dict) else {}) or {}
                score_text = (f"score {float(score['score_0_100']):.0f}/100, "
                              f"risk {100 * float(risk.get('actual_risk_percent', 0)):.1f}%. "
                              if score.get("status") == "available" else "")
                # Do not forward complete payloads, account identifiers or provider requests.
                self.alerter.send(f"{event.kind}: {event.observed_at_utc.isoformat()}; "
                                  f"{event.payload.get('symbol', '')} "
                                  f"{event.payload.get('reason', event.payload.get('error_type', ''))}. "
                                  + score_text +
                                  "Review the operator dashboard/local journal.")
                count += 1
            with closing(sqlite3.connect(self.journal.path)) as db, db:
                db.execute("UPDATE notification_cursor SET sequence=? WHERE id=1", (event.sequence,))
        return count

    def run(self, stop: Event) -> None:
        while not stop.is_set():
            try:
                self.once()
            except Exception:  # noqa: BLE001 - retain cursor for retry; never interrupt trading
                logging.getLogger("forex.alerts").warning("Phone alert delivery failed; retained for retry.")
            stop.wait(30)
