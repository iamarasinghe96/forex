"""Summarize actual paper heartbeat evidence without inventing elapsed uptime."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from itertools import pairwise
from typing import Any

from forex.domain import _require_utc
from forex.journal import JournalStore


def summarize_soak(journal: JournalStore, start: datetime, end: datetime,
                   maximum_heartbeat_gap_seconds: float = 120) -> dict[str, Any]:
    _require_utc(start, "start")
    _require_utc(end, "end")
    if end <= start or maximum_heartbeat_gap_seconds <= 0:
        raise ValueError("soak window and maximum heartbeat gap must be positive")
    counts: Counter[str] = Counter()
    health: list[tuple[datetime, dict[str, Any]]] = []
    errors: list[str] = []
    cursor = 0
    while events := journal.events("PAPER", after_sequence=cursor, limit=500):
        for event in events:
            cursor = event.sequence
            if not start <= event.observed_at_utc < end:
                continue
            counts[event.kind] += 1
            if event.kind == "health":
                health.append((event.observed_at_utc, dict(event.payload)))
            if event.kind in {"error", "alert"}:
                errors.append(event.event_id)
    clock_reversal = any(right[0] < left[0] for left, right in pairwise(health))
    ordered = sorted(health, key=lambda item: item[0])
    covered = 0.0
    gaps: list[dict[str, Any]] = []
    for left, right in pairwise(ordered):
        seconds = (right[0] - left[0]).total_seconds()
        if seconds > maximum_heartbeat_gap_seconds:
            gaps.append({"after_utc": left[0], "before_utc": right[0], "seconds": seconds})
        elif left[1].get("status") == right[1].get("status") == "RUNNING":
            covered += seconds
    first, last = (ordered[0][0], ordered[-1][0]) if ordered else (None, None)
    elapsed = (last - first).total_seconds() if first and last else 0.0
    versions = sorted({str(item[1].get("config_fingerprint", "UNRECORDED")) for item in ordered})
    codes = sorted({str(item[1].get("code_fingerprint", "UNRECORDED")) for item in ordered})
    return {"mode": "PAPER", "requested_start_utc": start, "requested_end_utc_exclusive": end,
            "first_observed_utc": first, "last_observed_utc": last,
            "observed_wall_clock_hours": elapsed / 3600,
            "running_intervals_supported_by_heartbeats_hours": covered / 3600,
            "maximum_allowed_heartbeat_gap_seconds": maximum_heartbeat_gap_seconds,
            "heartbeat_count": len(health), "event_counts": dict(counts),
            "unobserved_gaps": gaps, "clock_reversal_detected": clock_reversal,
            "config_fingerprints": versions, "code_fingerprints": codes,
            "incident_evidence_ids": errors,
            "state": "NO_ELAPSED_EVIDENCE" if elapsed == 0 else "EVIDENCE_REQUIRES_REVIEW",
            "operational_failures_resolved": False, "strategy_validated": False,
            "limitations": ["Heartbeat intervals support observation continuity, not proof of every broker or process event.",
                            "No observed interval before the first or after the last heartbeat is counted.",
                            "Errors, gaps, version changes and external recovery checks require operator review."]}
