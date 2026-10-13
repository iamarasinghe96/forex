"""Independent phone-alert delivery from durable journal evidence."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from threading import Event
from typing import Any

from forex.alerts import TelegramAlerter
from forex.journal import JournalStore
from forex.learning import trade_facts


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
                self.alerter.send(self.daily_recap(event.entity_id, event.payload))
                count += 1
            elif event.kind == "loss_prompt":
                p = event.payload
                pnl = float(p.get("pnl_aud") or 0)
                self.alerter.send_document(
                    str(p.get("file_name", "loss-review.txt")), str(p.get("prompt", "")),
                    f"Loss review for ChatGPT: {p.get('symbol', '')} {'Buy' if p.get('side') == 'LONG' else 'Sell'} "
                    f"{float(p.get('r') or 0):+.2f} R (A${pnl:+.2f}). Open the file and copy all the text, or share "
                    "the file to ChatGPT, and send it. Then paste ChatGPT's answer to Claude Code. The dashboard "
                    "also has a Copy button; /loss sends this file again.")
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

    def daily_recap(self, day: str, summary: Mapping[str, Any]) -> str:
        """Yesterday's closed trades by name, marked as a recap so it is not read as a new loss."""
        try:
            start = datetime.fromisoformat(day).replace(tzinfo=UTC)
        except ValueError:
            start = None
        trades = [e for e in self.journal.of_kind("PAPER", "trade_closed", since=start, limit=500)
                  if e.observed_at_utc.date().isoformat() == day] if start else []
        label = f"{start:%a %d %b}" if start else day
        if not trades and not summary.get("closed_trades"):
            return f"Daily recap for {label} (UTC day): no trades closed."
        parts = []
        for trade in trades:
            facts = trade_facts(trade.entity_id, trade.payload)
            side = "Buy" if str(trade.payload.get("direction")) == "LONG" else "Sell"
            parts.append(f"{str(trade.payload.get('symbol', '?')).split('.')[0]} {side} {trade.payload.get('reason', '')} "
                         + (f"{facts.r:+.2f} R " if facts else "")
                         + f"(A${float(trade.payload.get('pnl_aud', 0)):+.2f}, closed {trade.observed_at_utc:%H:%M} UTC)")
        return (f"Daily recap for {label} (UTC day). Already reported when they closed, not new: "
                f"{summary.get('closed_trades', len(trades))} trade(s) closed ({summary.get('wins', 0)} won, "
                f"{summary.get('losses', 0)} lost)" + (": " + "; ".join(parts) if parts else "")
                + f". Day total A${float(summary.get('realized_pnl_aud', 0)):+.2f}.")

    def run(self, stop: Event) -> None:
        while not stop.is_set():
            try:
                self.once()
            except Exception:  # noqa: BLE001 - retain cursor for retry; never interrupt trading
                logging.getLogger("forex.alerts").warning("Phone alert delivery failed; retained for retry.")
            stop.wait(30)
