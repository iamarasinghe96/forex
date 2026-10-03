"""Learning loop: score every closed paper trade, explain it, and apply operator-approved patches.

Three parts, all paper-only:

* Scoreboard - each closed trade updates "decision buckets" (pair, regime, session, ...). A
  bucket's score is a shrunk average R, so a few lucky trades cannot make it confident. Scores are
  kept per settings version, so trades taken under different settings are not pooled.
* Sizing - a bucket that is reliably losing (average plus ``evidence_z`` standard errors still
  below 0 R) scales new trades down; never up: the configured risk stays the ceiling.
* Strategy patches - a validated JSON change set limited to whitelisted settings and bounds.
  It never contains code; the operator approves it by Telegram and the runtime reloads it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from forex.config import AppConfig
from forex.domain import Candle, SymbolSpec, _require_utc
from forex.scoring import ScoreModel

PATCH_MARKER = "forex_patch"
LEGACY_VERSION = "legacy"  # Trades closed before settings versions were recorded.
# Per-trade results vary by about 1.06 R (13-year Dukascopy audit). A small bucket's own spread
# can look tiny by luck, so its standard error never uses less than this.
R_SPREAD_FLOOR = 1.0
SETUPS = Literal["TREND_CONTINUATION_BREAKOUT_PULLBACK", "RANGE_MEAN_REVERSION"]


# --------------------------------------------------------------------------- trade facts


@dataclass(frozen=True)
class TradeFacts:
    trade_id: str
    symbol: str
    side: str
    setup: str
    regime: str
    style: str
    sessions: tuple[str, ...]
    volatility: str
    conviction: float | None
    entry: float
    initial_stop: float
    exit: float
    exit_reason: str
    r: float
    pnl_aud: float
    opened_at_utc: str
    closed_at_utc: str
    strategy_version: str = LEGACY_VERSION
    score_band: str | None = None
    sizing_version: str | None = None

    def buckets(self) -> list[str]:
        keys = bucket_keys(self.symbol, self.side, self.setup, self.regime, self.style,
                           self.sessions, self.volatility)
        return keys + ([f"score:{self.score_band}"] if self.score_band else [])


def volatility_bucket(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    return "LOW" if value < 1 / 3 else "MEDIUM" if value < 2 / 3 else "HIGH"


def bucket_keys(symbol: str, side: str, setup: str, regime: str, style: str,
                sessions: Sequence[str], volatility: str) -> list[str]:
    """Decision buckets a trade belongs to; overlapping sessions count in each."""
    keys = ["all", f"pair:{symbol}", f"setup:{setup}", f"regime:{regime}", f"style:{style}",
            f"volatility:{volatility}", f"pair_side:{symbol}|{side}", f"pair_regime:{symbol}|{regime}"]
    return keys + [f"session:{s}" for s in (sessions or ("OFF_HOURS",))]


def candidate_keys(symbol: str, candidate: Mapping[str, Any]) -> list[str]:
    """Bucket keys for a not-yet-traded candidate (journal JSON form)."""
    keys = bucket_keys(symbol.upper(), str(candidate.get("side")), str(candidate.get("setup_type")),
                       str((candidate.get("h4_regime") or {}).get("label")),
                       str(candidate.get("trade_style")), tuple(candidate.get("session_context") or ()),
                       volatility_bucket(_float(candidate.get("volatility_context"))))
    band = (candidate.get("setup_score") or {}).get("band")
    return keys + ([f"score:{band}"] if band else [])


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def trade_facts(trade_id: str, payload: Mapping[str, Any]) -> TradeFacts | None:
    """Extract scoring facts from a trade_closed journal payload; None if provenance is missing."""
    provenance = payload.get("decision_provenance")
    intent = payload.get("intent")
    if not isinstance(provenance, Mapping) or not isinstance(intent, Mapping):
        return None
    candidate = (provenance.get("candidate") or {}).get("candidate") or {}
    entry, exit_, stop = _float(payload.get("entry")), _float(payload.get("exit")), _float(intent.get("stop"))
    if not candidate or entry is None or exit_ is None or stop is None or entry == stop:
        return None
    side = str(candidate.get("side") or intent.get("side"))
    sign = 1 if side == "LONG" else -1
    risk = ((provenance.get("risk_decision") or {}).get("risk") or {})
    conviction = _float((risk.get("conviction") or {}).get("final_conviction"))
    # Positions carry the broker name (e.g. USDJPY.a); buckets use the plain pair name.
    symbol = str(candidate.get("symbol") or payload.get("symbol", "?")).upper().split(".")[0]
    return TradeFacts(
        trade_id, symbol, side, str(candidate.get("setup_type")),
        str((candidate.get("h4_regime") or {}).get("label")), str(candidate.get("trade_style")),
        tuple(candidate.get("session_context") or ()), volatility_bucket(_float(candidate.get("volatility_context"))),
        conviction, entry, stop, exit_, str(payload.get("reason", "?")),
        (exit_ - entry) * sign / abs(entry - stop), float(payload.get("pnl_aud", 0)),
        str(payload.get("opened_at_utc", "")), str(payload.get("closed_at_utc", "")),
        str((provenance.get("candidate") or {}).get("strategy_version") or LEGACY_VERSION),
        ((provenance.get("candidate") or {}).get("setup_score") or {}).get("band"),
        (provenance.get("candidate") or {}).get("sizing_version"),
    )


def strategy_version(config: AppConfig, model_sha256: str | None = None) -> str:
    """Short fingerprint of the settings that decide which trades are taken and how they exit.

    Risk percent and learning settings are left out: R results do not depend on them.
    """
    settings = knobs(config)
    identity = {"analysis": settings["analysis"], "exits": settings["exits"]}
    if config.scoring.enabled or config.scoring.shadow:
        if model_sha256 is not None:
            if model_sha256:
                identity["setup_model_sha256"] = model_sha256
        else:
            try:
                identity["setup_model_sha256"] = ScoreModel.load(config.scoring.model_path).sha256
            except (OSError, ValueError, KeyError, TypeError):
                pass  # Missing shadow model preserves the existing strategy identity.
    raw = json.dumps(identity, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:8]


def price_path(facts: TradeFacts, candles: Sequence[Candle]) -> dict[str, float | int]:
    """Best and worst excursion in R while the trade was open (H1 bars, approximate)."""
    opened, closed = datetime.fromisoformat(facts.opened_at_utc), datetime.fromisoformat(facts.closed_at_utc)
    bars = [c for c in candles if opened - c.timeframe.duration < c.timestamp_utc <= closed]
    risk = abs(facts.entry - facts.initial_stop)
    if not bars or risk <= 0:
        return {}
    sign = 1 if facts.side == "LONG" else -1
    best = max(float(c.high) for c in bars) if sign > 0 else min(float(c.low) for c in bars)
    worst = min(float(c.low) for c in bars) if sign > 0 else max(float(c.high) for c in bars)
    return {"bars_held": len(bars), "best_excursion_r": round((best - facts.entry) * sign / risk, 2),
            "worst_excursion_r": round((worst - facts.entry) * sign / risk, 2)}


# --------------------------------------------------------------------------- scoreboard


@dataclass(frozen=True)
class BucketScore:
    bucket: str
    trades: int
    wins: int
    losses: int
    total_r: float
    score_r: float        # Shrunk average R: total / (trades + prior), i.e. a prior of 0 R.
    confidence: float     # trades / (trades + prior), 0..1
    std_error: float = 0.0  # Standard error of the average R (spread floored at R_SPREAD_FLOOR).

    @property
    def average_r(self) -> float:
        return self.total_r / self.trades if self.trades else 0.0

    def reliably_losing(self, z: float) -> bool:
        """True when the average stays below 0 R even after adding ``z`` standard errors."""
        return self.trades > 0 and self.average_r + z * self.std_error < 0

    def line(self) -> str:
        return (f"{self.bucket}: {self.trades} trades, {self.wins}W/{self.losses}L, "
                f"avg {self.average_r:+.2f} ± {self.std_error:.2f} R, "
                f"score {self.score_r:+.2f} R, evidence weight {self.confidence:.0%}")


def bucket_scores(trades: Sequence[TradeFacts], prior: int) -> dict[str, BucketScore]:
    totals: dict[str, list[float]] = {}
    for facts in trades:
        for key in facts.buckets():
            totals.setdefault(key, []).append(facts.r)
    scores = {}
    for key, rs in totals.items():
        n, total = len(rs), sum(rs)
        variance = sum((r - total / n) ** 2 for r in rs) / (n - 1) if n > 1 else 0.0
        error = math.sqrt(max(variance, R_SPREAD_FLOOR ** 2) / n)
        scores[key] = BucketScore(key, n, sum(r > 0 for r in rs), sum(r < 0 for r in rs), total,
                                  total / (n + prior), n / (n + prior), error)
    return scores


@dataclass(frozen=True)
class VersionSummary:
    version: str
    trades: int
    total_r: float
    first_closed_utc: str
    last_closed_utc: str

    def line(self) -> str:
        return (f"settings {self.version}: {self.trades} trades, total {self.total_r:+.2f} R, "
                f"{self.first_closed_utc[:10]} to {self.last_closed_utc[:10]}")


class LearningStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # learning_scores held pooled totals before settings versions existed; scores are now
        # computed from learning_trades. The table is kept so older databases open unchanged.
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS learning_trades (
                trade_id TEXT PRIMARY KEY, facts_json TEXT NOT NULL, r REAL NOT NULL,
                review_json TEXT, recorded_at_utc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS learning_scores (
                bucket TEXT PRIMARY KEY, trades INTEGER NOT NULL, wins INTEGER NOT NULL,
                losses INTEGER NOT NULL, total_r REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS learning_cursor (id INTEGER PRIMARY KEY CHECK(id=1), sequence INTEGER NOT NULL);
            INSERT OR IGNORE INTO learning_cursor VALUES (1, 0);
            CREATE TABLE IF NOT EXISTS strategy_patches (
                id INTEGER PRIMARY KEY, status TEXT NOT NULL, patch_json TEXT NOT NULL,
                summary TEXT NOT NULL, overlay_before TEXT, overlay_after TEXT,
                created_at_utc TEXT NOT NULL, decided_at_utc TEXT);
            CREATE TABLE IF NOT EXISTS telegram_cursor (id INTEGER PRIMARY KEY CHECK(id=1), update_id INTEGER NOT NULL);
            INSERT OR IGNORE INTO telegram_cursor VALUES (1, 0);
            """)

    # Trades ----------------------------------------------------------------
    def record_trade(self, facts: TradeFacts, now: datetime) -> bool:
        """Add a closed trade to every bucket once; False if it was already recorded."""
        _require_utc(now, "now")
        with closing(sqlite3.connect(self.path)) as db, db:
            if db.execute("SELECT 1 FROM learning_trades WHERE trade_id=?", (facts.trade_id,)).fetchone():
                return False
            db.execute("INSERT INTO learning_trades VALUES (?,?,?,NULL,?)",
                       (facts.trade_id, json.dumps(facts.__dict__), facts.r, now.isoformat()))
        return True

    def trades(self, version: str | None = None) -> list[TradeFacts]:
        """Recorded trades, oldest first; only those taken under ``version`` when given."""
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT facts_json FROM learning_trades ORDER BY recorded_at_utc, trade_id").fetchall()
        result = []
        for (raw,) in rows:
            data = json.loads(raw)
            data["sessions"] = tuple(data.get("sessions") or ())
            data.setdefault("strategy_version", LEGACY_VERSION)
            if version is None or data["strategy_version"] == version:
                result.append(TradeFacts(**data))
        return result

    def save_review(self, trade_id: str, review: Mapping[str, Any]) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE learning_trades SET review_json=? WHERE trade_id=?",
                       (json.dumps(review), trade_id))

    def recent_reviews(self, limit: int = 20) -> list[dict[str, Any]]:
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute("SELECT facts_json, review_json FROM learning_trades "
                              "ORDER BY recorded_at_utc DESC LIMIT ?", (limit,)).fetchall()
        return [{"facts": json.loads(f), "review": json.loads(r) if r else None} for f, r in rows]

    def scores(self, prior: int, version: str | None = None, *,
               sizing: bool = False) -> dict[str, BucketScore]:
        """Bucket scores for one settings version (None pools every version)."""
        if sizing:
            # Shadow model changes must not reset or contaminate existing sizing evidence.
            trades = [t for t in self.trades() if version is None or (t.sizing_version or t.strategy_version) == version]
            return bucket_scores(trades, prior)
        return bucket_scores(self.trades(version), prior)

    def versions(self) -> list[VersionSummary]:
        """One line per settings version that has closed trades, oldest first."""
        groups: dict[str, list[TradeFacts]] = {}
        for facts in self.trades():
            groups.setdefault(facts.strategy_version, []).append(facts)
        return [VersionSummary(v, len(fs), sum(f.r for f in fs), min(f.closed_at_utc for f in fs),
                               max(f.closed_at_utc for f in fs)) for v, fs in groups.items()]

    def cursor(self) -> int:
        with closing(sqlite3.connect(self.path)) as db, db:
            return int(db.execute("SELECT sequence FROM learning_cursor WHERE id=1").fetchone()[0])

    def set_cursor(self, sequence: int) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE learning_cursor SET sequence=? WHERE id=1", (sequence,))

    # Patches ---------------------------------------------------------------
    def add_patch(self, patch: StrategyPatch, summary: str, now: datetime) -> int:
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute("INSERT INTO strategy_patches VALUES (NULL,'PENDING',?,?,NULL,NULL,?,NULL)",
                                (patch.model_dump_json(exclude_unset=True), summary, now.isoformat()))
            return int(cursor.lastrowid or 0)

    def patch(self, patch_id: int) -> tuple[str, StrategyPatch] | None:
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT status, patch_json FROM strategy_patches WHERE id=?", (patch_id,)).fetchone()
        return (str(row[0]), StrategyPatch.model_validate_json(row[1])) if row else None

    def decide(self, patch_id: int, status: str, now: datetime, before: Mapping[str, Any] | None = None,
               after: Mapping[str, Any] | None = None) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE strategy_patches SET status=?, decided_at_utc=?, overlay_before=?, overlay_after=? "
                       "WHERE id=?", (status, now.isoformat(), None if before is None else json.dumps(before),
                                      None if after is None else json.dumps(after), patch_id))

    def last_applied(self) -> tuple[int, dict[str, Any]] | None:
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT id, overlay_before FROM strategy_patches WHERE status='APPLIED' "
                             "ORDER BY id DESC LIMIT 1").fetchone()
        return (int(row[0]), json.loads(row[1] or "{}")) if row else None

    def telegram_offset(self) -> int:
        with closing(sqlite3.connect(self.path)) as db, db:
            return int(db.execute("SELECT update_id FROM telegram_cursor WHERE id=1").fetchone()[0])

    def set_telegram_offset(self, update_id: int) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE telegram_cursor SET update_id=? WHERE id=1", (update_id,))


@dataclass(frozen=True)
class SizingDecision:
    factor: float
    skip: bool
    score_r: float | None
    buckets: tuple[str, ...]
    reason: str


def sizing_decision(scores: Mapping[str, BucketScore], keys: Sequence[str], *, min_trades: int,
                    min_factor: float, skip_below_r: float | None, evidence_z: float = 0.0) -> SizingDecision:
    """Scale a new trade down by its reliably losing buckets. Never above 1: risk config is the ceiling.

    A bucket counts only with at least ``min_trades`` trades and an average that stays below 0 R
    after adding ``evidence_z`` standard errors, so ordinary losing streaks do not shrink trades.
    """
    enough = [scores[k] for k in keys if k in scores and scores[k].trades >= min_trades]
    if not enough:
        return SizingDecision(1.0, False, None, (), f"not enough history yet (needs {min_trades} trades per bucket)")
    known = [b for b in enough if b.reliably_losing(evidence_z)]
    if not known:
        return SizingDecision(1.0, False, None, (), f"no bucket is reliably losing (average + {evidence_z:g} "
                              "standard errors below 0 R); full size")
    weight = sum(b.trades for b in known)
    score = sum(b.score_r * b.trades for b in known) / weight
    names = tuple(b.bucket for b in known)
    if skip_below_r is not None and score < skip_below_r:
        return SizingDecision(0.0, True, score, names, f"score {score:+.2f} R is below the skip level {skip_below_r:+.2f} R")
    factor = max(min_factor, min(1.0, 1 + 2 * score))
    return SizingDecision(factor, False, score, names, f"score {score:+.2f} R -> size x{factor:.2f}")


def scale_plan(decision: Any, factor: float, spec: SymbolSpec) -> Any:
    """Reduce an approved context decision's volume by ``factor`` (same rounding as AI reductions)."""
    plan = decision.plan
    if plan is None or factor >= 1:
        return decision
    volume = (plan.volume * Decimal(str(factor)) / spec.volume_step).to_integral_value(rounding=ROUND_FLOOR) * spec.volume_step
    if volume < spec.volume_min or volume <= 0:
        volume = spec.volume_min  # Smallest tradable size still respects the configured ceiling.
    if volume >= plan.volume:
        return decision
    fraction = volume / plan.volume
    reduced = replace(plan, volume=volume, actual_risk_amount=plan.actual_risk_amount * fraction,
                      actual_risk_percent=plan.actual_risk_percent * fraction)
    return replace(decision, plan=reduced, rationale=f"{decision.rationale} | learning size x{fraction:.2f}")


# --------------------------------------------------------------------------- strategy patches


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisPatch(_Strict):
    high_volatility_blocks_trend: bool = True
    trend_efficiency_window: int | None = Field(default=None, ge=3, le=40)
    trend_threshold: float = Field(default=0.55, ge=0.3, le=0.9)
    setup_score_threshold: float = Field(default=0.45, ge=0.2, le=0.9)
    swing_trend_threshold: float = Field(default=0.68, ge=0.3, le=0.95)
    allowed_setups: list[SETUPS] = Field(default_factory=list, min_length=1)


class ExitsPatch(_Strict):
    target_reward_risk: float | None = Field(default=None, ge=1.5, le=20)
    atr_trailing_multiple: float | None = Field(default=None, ge=1, le=6)


class RiskPatch(_Strict):
    risk_percent_per_trade: float = Field(default=5, ge=0.25, le=5)


class LearningPatch(_Strict):
    apply_to_sizing: bool = True
    prior_trades: int = Field(default=20, ge=5, le=200)
    min_trades: int = Field(default=10, ge=3, le=200)
    min_factor: float = Field(default=0.25, ge=0.1, le=1)
    skip_below_r: float | None = Field(default=None, ge=-1, le=0)


class StrategyPatch(_Strict):
    """Everything an approved learning review may change. Anything else is rejected."""

    forex_patch: Literal[1]
    summary: str = Field(min_length=1, max_length=600)
    analysis: AnalysisPatch | None = None
    exits: ExitsPatch | None = None
    risk: RiskPatch | None = None
    learning: LearningPatch | None = None
    disabled_pairs: list[str] | None = Field(default=None, max_length=10)
    research_requests: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def bounded_text(self) -> StrategyPatch:
        if any(len(item) > 400 for item in self.research_requests):
            raise ValueError("each research request must be at most 400 characters")
        if self.disabled_pairs and any(not re.fullmatch(r"[A-Z]{6}", p) for p in self.disabled_pairs):
            raise ValueError("disabled_pairs must be 6-letter pair names such as EURUSD")
        return self

    def changes(self) -> dict[str, Any]:
        """Only the fields the reply actually set (explicit nulls included)."""
        data = self.model_dump(exclude_unset=True)
        return {k: v for k, v in data.items() if k not in {"forex_patch", "summary", "research_requests"}}


def parse_patch(text: str) -> StrategyPatch:
    """Find the JSON object in a pasted Claude reply (prose and code fences are ignored)."""
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates = fenced or ([text[text.find("{"):text.rfind("}") + 1]] if "{" in text else [])
    errors = []
    for raw in candidates:
        if PATCH_MARKER not in raw:
            continue
        try:
            return StrategyPatch.model_validate_json(raw)
        except ValidationError as exc:
            errors.append("; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5]))
    if errors:
        raise ValueError("The change set was rejected: " + errors[0])
    raise ValueError(f"No JSON change set with \"{PATCH_MARKER}\" was found in the message.")


def merge_overlay(overlay: Mapping[str, Any], patch: StrategyPatch) -> dict[str, Any]:
    merged: dict[str, Any] = json.loads(json.dumps(overlay))
    for section, value in patch.changes().items():
        if isinstance(value, dict):
            merged.setdefault(section, {}).update(value)
        else:
            merged[section] = value
    return merged


def apply_overlay(base: AppConfig, overlay: Mapping[str, Any]) -> AppConfig:
    """Effective configuration = config.yaml + approved overlay (validated as a whole)."""
    if not overlay:
        return base
    data = base.model_dump()
    data["analysis"].update(overlay.get("analysis", {}))
    exits = overlay.get("exits", {})
    for key in ("target_reward_risk", "atr_trailing_multiple"):
        if key in exits:
            data["paper"][key] = exits[key]
    if "risk_percent_per_trade" in overlay.get("risk", {}):
        value = overlay["risk"]["risk_percent_per_trade"]
        data["risk"]["conviction_risk_percent"] = {"low": value, "medium": value, "high": value}
    data["learning"].update(overlay.get("learning", {}))
    if overlay.get("disabled_pairs") is not None:
        data["learning"]["disabled_pairs"] = list(overlay["disabled_pairs"])
    return AppConfig.model_validate(data)


def overlay_path(paper_database: Path) -> Path:
    """Approved changes live beside the paper account they were learned on."""
    return paper_database.with_name(paper_database.stem + ".strategy-overlay.json")


def read_overlay(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("strategy overlay must be a JSON object")  # noqa: TRY004 - callers treat as invalid input
    return value


def write_overlay(path: Path, overlay: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(overlay, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def knobs(config: AppConfig) -> dict[str, Any]:
    """The settings a learning review may change, in patch terms."""
    a, p, r, lc = config.analysis, config.paper, config.risk, config.learning
    risks = sorted(set(r.conviction_risk_percent.values()))
    return {
        "analysis": {"high_volatility_blocks_trend": a.high_volatility_blocks_trend,
                     "trend_efficiency_window": a.trend_efficiency_window,
                     "trend_threshold": a.trend_threshold, "setup_score_threshold": a.setup_score_threshold,
                     "swing_trend_threshold": a.swing_trend_threshold, "allowed_setups": list(a.allowed_setups)},
        "exits": {"target_reward_risk": p.target_reward_risk, "atr_trailing_multiple": p.atr_trailing_multiple},
        "risk": {"risk_percent_per_trade": risks[0] if len(risks) == 1 else r.conviction_risk_percent},
        "learning": {"apply_to_sizing": lc.apply_to_sizing, "prior_trades": lc.prior_trades,
                     "min_trades": lc.min_trades, "min_factor": lc.min_factor, "skip_below_r": lc.skip_below_r},
        "disabled_pairs": list(lc.disabled_pairs),
        "pairs": list(config.broker.symbols),
    }


def describe_changes(before: AppConfig, after: AppConfig) -> list[str]:
    old, new = _flatten(knobs(before)), _flatten(knobs(after))
    return [f"{key}: {old.get(key)} -> {new.get(key)}" for key in sorted(new) if old.get(key) != new.get(key)]


def _flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, item in value.items():
        name = f"{prefix}{key}"
        if isinstance(item, Mapping) and key != "risk_percent_per_trade":
            flat.update(_flatten(item, name + "."))
        else:
            flat[name] = item
    return flat


# --------------------------------------------------------------------------- prompts


class PostMortem(_Strict):
    summary: str = Field(min_length=1, max_length=500)
    likely_causes: list[str] = Field(default_factory=list, max_length=5)
    lesson: str = Field(min_length=1, max_length=400)
    category: Literal["trend_followed_through", "stopped_by_noise", "late_entry", "reversal",
                      "news_or_volatility_spike", "trailing_or_target_exit", "other"]


def postmortem_payload(facts: TradeFacts, path: Mapping[str, Any], scores: Mapping[str, BucketScore]) -> str:
    return json.dumps({"trade": {k: v for k, v in facts.__dict__.items() if k != "trade_id"},
                       "price_path_while_open": path,
                       "bucket_scores_after_this_trade": [scores[k].line() for k in facts.buckets() if k in scores],
                       "response_schema": PostMortem.model_json_schema()}, sort_keys=True, default=str)


def review_prompt(config: AppConfig, store: LearningStore, instructions: str, now: datetime) -> str:
    """The text the operator pastes into Claude; the reply comes back as a StrategyPatch."""
    version = strategy_version(config)
    scores = sorted(store.scores(config.learning.prior_trades, version).values(),
                    key=lambda b: (-b.trades, b.bucket))
    lines = [instructions.strip(), "", f"Generated {now:%Y-%m-%d %H:%M} UTC by the paper bot.", "",
             f"## Current settings, version {version} (you may change only these)", "```json",
             json.dumps(knobs(config), indent=2), "```", "",
             (f"## Scoreboard for settings {version} (avg ± one standard error; score = total R / "
              f"(trades + {config.learning.prior_trades}); evidence weight = trades / (trades + prior), "
              "not a probability of profit)")]
    lines += [f"- {b.line()}" for b in scores] or ["- No closed trades under these settings yet."]
    lines += ["", "## Results by settings version (trades are never pooled across versions)"]
    lines += [f"- {v.line()}" for v in store.versions()] or ["- None yet."]
    lines += ["", "## Recent trades with the bot's own review (newest first)"]
    for item in store.recent_reviews(20):
        f, review = item["facts"], item["review"] or {}
        lines.append(f"- {f['closed_at_utc'][:16]} [{f.get('strategy_version', LEGACY_VERSION)}] "
                     f"{f['symbol']} {f['side']} {f['regime']} {f['style']} "
                     f"exit {f['exit_reason']} {f['r']:+.2f} R | {review.get('category', 'no review')}: "
                     f"{review.get('summary', '')} Lesson: {review.get('lesson', '')}")
    if not store.recent_reviews(1):
        lines.append("- None yet.")
    lines += ["", "## Allowed change set (JSON schema)", "```json",
              json.dumps(StrategyPatch.model_json_schema(), indent=1), "```"]
    return "\n".join(lines) + "\n"
