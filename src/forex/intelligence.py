"""Research-only diagnosis and immutable version gates. Never changes trading configuration."""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from forex.attribution import attribute
from forex.domain import _require_utc
from forex.journal import JournalStore
from forex.serialization import canonical_json

Stage = Literal["HISTORICAL", "RECENT", "WALK_FORWARD", "OOS", "SHADOW", "PAPER"]
STAGES: tuple[Stage, ...] = ("HISTORICAL", "RECENT", "WALK_FORWARD", "OOS", "SHADOW", "PAPER")


def diagnose(journal: JournalStore, mode: str, start: datetime, end: datetime) -> dict[str, Any]:
    _require_utc(start, "start")
    _require_utc(end, "end")
    if end <= start:
        raise ValueError("diagnosis requires an increasing UTC window")
    kinds: Counter[str] = Counter()
    symbols: Counter[str] = Counter()
    evidence: dict[str, dict[str, Any]] = {}
    outcomes: list[Decimal] = []
    cursor = 0
    digest = hashlib.sha256()
    while events := journal.events(mode, after_sequence=cursor, limit=500):
        for event in events:
            cursor = event.sequence
            if not start <= event.observed_at_utc < end:
                continue
            kinds[event.kind] += 1
            symbols[str(event.payload.get("symbol", "ACCOUNT"))] += 1
            value = {**event.payload, "kind": event.kind}
            evidence[event.event_id] = value
            digest.update(f"{event.event_id}:{event.payload_hash}\n".encode())
            if event.kind == "trade_closed":
                outcomes.append(Decimal(str(event.payload["pnl_aud"])))
    return {"mode": mode, "start_utc": start, "end_utc_exclusive": end,
            "source_fingerprint": digest.hexdigest(), "event_counts": dict(kinds),
            "symbol_counts": dict(symbols), "evidence_ids": sorted(evidence),
            "attribution": attribute(evidence), "closed_trade_count": len(outcomes),
            "recorded_pnl_aud": sum(outcomes) if outcomes else None,
            "limitations": ["Descriptive observations are not causal proof.",
                            "Closed trades alone exclude rejected and no-trade opportunity evidence.",
                            "No automatic parameter mutation or reactive trading veto.",
                            "Simulated costs and broker alignment require independent verification."],
            "production_action": "NONE", "strategy_validated": False}


class AcceptanceCriteria(BaseModel):
    """Pre-registered, explicit experiment gates; no guessed promotion thresholds."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    minimum_history_years: float = Field(ge=5, allow_inf_nan=False)
    minimum_walk_forward_folds: int = Field(ge=1)
    minimum_out_of_sample_trades: int = Field(ge=1)
    minimum_shadow_hours: float = Field(gt=0, allow_inf_nan=False)
    minimum_paper_hours: float = Field(gt=0, allow_inf_nan=False)
    minimum_net_expectancy_r: float = Field(allow_inf_nan=False)
    maximum_drawdown_percent: float = Field(gt=0, le=100, allow_inf_nan=False)


class ExperimentEvidence(BaseModel):
    """Producer report contract. Claims remain attributable to the report producer."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    version_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    stage: Stage
    producer: str = Field(min_length=1)
    code_sha: str = Field(pattern=r"^[a-f0-9]{40}$")
    dataset_fingerprint: str = Field(min_length=1)
    start_utc: datetime
    end_utc: datetime
    generated_at_utc: datetime
    baseline_comparison: str = Field(min_length=1)
    costs_complete: bool
    broker_h4_alignment_verified: bool
    future_data_excluded: bool
    history_years: float = Field(ge=0, allow_inf_nan=False)
    walk_forward_folds: int = Field(ge=0)
    completed_trades: int = Field(ge=0)
    net_expectancy_r: float = Field(allow_inf_nan=False)
    maximum_drawdown_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    untouched_oos: bool
    real_elapsed_hours: float = Field(ge=0, allow_inf_nan=False)
    operational_failures_resolved: bool
    source_artifacts: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_times(self) -> ExperimentEvidence:
        for value in (self.start_utc, self.end_utc, self.generated_at_utc):
            _require_utc(value, "evidence time")
        if not self.start_utc < self.end_utc <= self.generated_at_utc:
            raise ValueError("evidence requires start < end <= generation")
        if self.real_elapsed_hours > (self.end_utc - self.start_utc).total_seconds() / 3600:
            raise ValueError("elapsed evidence cannot exceed its actual wall-clock interval")
        return self


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


class ExperimentRegistry:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS experiments (version_hash TEXT PRIMARY KEY,
                    hypothesis_json TEXT NOT NULL, criteria_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS experiment_evidence (version_hash TEXT NOT NULL,
                    stage TEXT NOT NULL, report_path TEXT NOT NULL, report_hash TEXT NOT NULL,
                    attached_at TEXT NOT NULL, PRIMARY KEY(version_hash,stage));
                CREATE TABLE IF NOT EXISTS promotion_reviews (version_hash TEXT PRIMARY KEY,
                    reviewer TEXT NOT NULL, review_reference TEXT NOT NULL, evidence_hash TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL);
            """)

    def propose(self, diagnosis: dict[str, Any], hypothesis: str,
                parameters: dict[str, Any], criteria: AcceptanceCriteria, now: datetime) -> str:
        _require_utc(now, "now")
        if not hypothesis.strip() or not diagnosis.get("evidence_ids") or not parameters:
            raise ValueError("hypothesis requires source evidence, rationale and an explicit candidate parameter version")
        # Store the complete snapshot so later journal edits cannot rewrite the hypothesis basis.
        proposal = canonical_json({"diagnosis": diagnosis, "hypothesis": hypothesis,
                                   "candidate_parameters": parameters})
        identity = hashlib.sha256((proposal + criteria.model_dump_json()).encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR IGNORE INTO experiments VALUES (?,?,?,?)",
                       (identity, proposal, criteria.model_dump_json(), now.isoformat()))
        return identity

    def _experiment(self, version: str) -> tuple[AcceptanceCriteria, datetime]:
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT criteria_json,created_at FROM experiments WHERE version_hash=?",
                             (version,)).fetchone()
        if not row:
            raise ValueError("unknown immutable experiment version")
        return AcceptanceCriteria.model_validate_json(row[0]), datetime.fromisoformat(row[1])

    def attach(self, version: str, report: Path, now: datetime) -> None:
        _require_utc(now, "now")
        _, created = self._experiment(version)
        value = ExperimentEvidence.model_validate_json(report.read_text(encoding="utf-8"))
        if value.version_hash != version or not created <= value.generated_at_utc <= now:
            raise ValueError("report is bound to another version or was not generated after pre-registration")
        self._check_sources(value, report.parent)
        with closing(sqlite3.connect(self.path)) as db, db:
            existing = db.execute("SELECT report_hash FROM experiment_evidence WHERE version_hash=? AND stage=?",
                                  (version, value.stage)).fetchone()
            digest = file_hash(report)
            if existing and existing[0] != digest:
                raise ValueError("stage evidence is immutable; create a new experiment for revised results")
            db.execute("INSERT OR IGNORE INTO experiment_evidence VALUES (?,?,?,?,?)",
                       (version, value.stage, str(report.resolve()), digest, now.isoformat()))

    @staticmethod
    def _check_sources(value: ExperimentEvidence, directory: Path) -> None:
        for name, expected in value.source_artifacts.items():
            if file_hash(directory / name) != expected:
                raise ValueError("source artifact hash does not match evidence")

    def evaluate(self, version: str, now: datetime) -> dict[str, Any]:
        _require_utc(now, "now")
        criteria, created = self._experiment(version)
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT stage,report_path,report_hash,attached_at FROM experiment_evidence WHERE version_hash=?",
                              (version,)).fetchall()
        reports: dict[str, ExperimentEvidence] = {}
        issues: list[str] = []
        fingerprints: dict[str, str] = {}
        for stage, name, expected, attached in rows:
            try:
                path = Path(name)
                if file_hash(path) != expected:
                    raise ValueError("report changed")
                value = ExperimentEvidence.model_validate_json(path.read_text(encoding="utf-8"))
                self._check_sources(value, path.parent)
                if value.version_hash != version or not created <= value.generated_at_utc <= now:
                    raise ValueError("version/time binding invalid")
                reports[stage] = value
                fingerprints[stage] = expected
            except (OSError, ValueError):
                issues.append(f"{stage}: artifact missing, changed or invalid")
        for stage in STAGES:
            r = reports.get(stage)
            if r is None:
                issues.append(f"{stage}: evidence missing")
                continue
            if not (r.costs_complete and r.broker_h4_alignment_verified and r.future_data_excluded):
                issues.append(f"{stage}: cost, H4 alignment or future-data gate unresolved")
            if r.net_expectancy_r < criteria.minimum_net_expectancy_r or r.maximum_drawdown_percent > criteria.maximum_drawdown_percent:
                issues.append(f"{stage}: pre-registered performance criteria failed")
            if stage == "HISTORICAL" and r.history_years < criteria.minimum_history_years:
                issues.append("HISTORICAL: insufficient genuine history")
            if stage == "WALK_FORWARD" and r.walk_forward_folds < criteria.minimum_walk_forward_folds:
                issues.append("WALK_FORWARD: insufficient completed folds")
            if stage == "OOS" and (not r.untouched_oos or r.completed_trades < criteria.minimum_out_of_sample_trades):
                issues.append("OOS: untouched evidence or sample requirement missing")
            required = criteria.minimum_shadow_hours if stage == "SHADOW" else criteria.minimum_paper_hours
            if stage in {"SHADOW", "PAPER"} and (r.start_utc < created or r.real_elapsed_hours < required or not r.operational_failures_resolved):
                issues.append(f"{stage}: real elapsed/operational evidence insufficient")
        historical, recent, oos = reports.get("HISTORICAL"), reports.get("RECENT"), reports.get("OOS")
        if oos and any(r and r.end_utc > oos.start_utc for r in (historical, recent, reports.get("WALK_FORWARD"))):
            issues.append("OOS: training/recent/walk-forward window overlaps final holdout")
        for previous, following in (("OOS", "SHADOW"), ("SHADOW", "PAPER")):
            before, after = reports.get(previous), reports.get(following)
            if before and after and before.end_utc > after.start_utc:
                issues.append(f"{following}: starts before {previous} evidence finishes")
        evidence_hash = hashlib.sha256(canonical_json(fingerprints).encode()).hexdigest()
        return {"version_hash": version, "state": "BLOCKED" if issues else "READY_FOR_OPERATOR_REVIEW",
                "issues": issues, "evidence_hash": evidence_hash, "production_action": "NONE",
                "claims": "Artifact integrity and declared gates checked; report producer assertions still require independent review."}

    def record_review(self, version: str, reviewer: str, review_reference: str, now: datetime) -> None:
        result = self.evaluate(version, now)
        if result["issues"] or not reviewer.strip() or not review_reference.strip():
            raise ValueError("promotion review requires complete evidence and an explicit operator review reference")
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO promotion_reviews VALUES (?,?,?,?,?)",
                       (version, reviewer, review_reference, result["evidence_hash"], now.isoformat()))
        # Deliberately no config writes, branch merges, broker calls or production activation.
