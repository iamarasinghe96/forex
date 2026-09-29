"""Constrained context review; unavailable providers preserve deterministic allowances."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from forex.config import ContextConfig, ContextProviderConfig
from forex.domain import SymbolSpec, _require_utc
from forex.risk import DecisionStatus, PositionRiskPlan, RiskDecision


class ContextSecrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FOREX_", extra="ignore")
    groq_api_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    openrouter_api_key: SecretStr = SecretStr("")


class ReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    verdict: Literal["approve", "reject", "reduce_size"]
    volume_fraction: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    rationale: str = Field(min_length=1, max_length=4000)
    evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> ReviewResponse:
        expected = {"approve": Decimal(1), "reject": Decimal(0)}
        if self.verdict in expected and self.volume_fraction != expected[self.verdict]:
            raise ValueError("verdict/fraction mismatch")
        if self.verdict == "reduce_size" and not 0 < self.volume_fraction < 1:
            raise ValueError("reduction requires fraction strictly inside 0..1")
        if self.verdict != "approve" and not self.evidence_ids:
            raise ValueError("veto/reduction needs supplied evidence")
        return self


@dataclass(frozen=True)
class ProviderReply:
    content: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    reported_cost_usd: Decimal | None = None


class ContextProvider(Protocol):
    def complete(self, config: ContextProviderConfig, prompt: str,
                 payload: str) -> ProviderReply: ...


class ProviderFailure(RuntimeError):
    """Sanitized failure; provider bodies/headers and credentials are never logged."""


ENDPOINTS = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}


class HTTPContextProvider:
    def __init__(self, config: ContextConfig, secrets: ContextSecrets,
                 client: httpx.Client | None = None):
        self.config, self.secrets, self.client = config, secrets, client

    def complete(self, config: ContextProviderConfig, prompt: str,
                 payload: str) -> ProviderReply:
        key = getattr(self.secrets, f"{config.name}_api_key").get_secret_value()
        if not key:
            raise ProviderFailure("CREDENTIAL_NOT_CONFIGURED")
        body = {"model": config.model, "stream": False,
                "messages": [{"role": "system", "content": prompt},
                             {"role": "user", "content": payload}],
                "response_format": {"type": "json_object"},
                "max_tokens": self.config.max_output_tokens}
        try:
            if self.client is None:
                with httpx.Client(timeout=self.config.timeout_seconds, follow_redirects=False) as c:
                    response = c.post(ENDPOINTS[config.name], json=body,
                                      headers={"Authorization": f"Bearer {key}"})
            else:
                response = self.client.post(ENDPOINTS[config.name], json=body,
                                           headers={"Authorization": f"Bearer {key}"},
                                           timeout=self.config.timeout_seconds)
            if response.status_code != 200:
                raise ProviderFailure(f"HTTP_{response.status_code}")
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content must be text")
            usage = data.get("usage") or {}
            counts = [usage.get("prompt_tokens"), usage.get("completion_tokens")]
            if any(v is not None and (type(v) is not int or v < 0) for v in counts):
                raise ValueError("invalid token usage")
            cost = Decimal(str(usage["cost"])) if usage.get("cost") is not None else None
            if cost is not None and (not cost.is_finite() or cost < 0):
                raise ValueError("invalid reported cost")
            return ProviderReply(content, str(data.get("model", config.model)),
                                 counts[0], counts[1], cost)
        except httpx.HTTPError:
            raise ProviderFailure("TRANSPORT_FAILURE") from None
        except (KeyError, IndexError, TypeError, ValueError, ArithmeticError):
            raise ProviderFailure("MALFORMED_PROVIDER_RESPONSE") from None


@dataclass(frozen=True)
class ContextDecision:
    risk_decision_id: str
    status: str
    plan: PositionRiskPlan | None
    rationale: str
    provider: str | None = None
    model: str | None = None
    prompt_hash: str | None = None
    input_hash: str | None = None
    cached: bool = False
    alert_required: bool = False


def apply_review(risk: RiskDecision, review: ReviewResponse, spec: SymbolSpec) -> ContextDecision:
    """Context has no fields capable of loosening stops, objectives, or risk policy."""
    plan = risk.permitted_position_plan
    if risk.status is not DecisionStatus.ELIGIBLE or plan is None:
        return ContextDecision(risk.decision_id, "DETERMINISTIC_BLOCK", None,
                               "Layer 5 blocked this proposal.")
    if review.verdict == "reject":
        return ContextDecision(risk.decision_id, "CONTEXT_REJECTED", None, review.rationale)
    if review.verdict == "approve":
        return ContextDecision(risk.decision_id, "APPROVED", plan, review.rationale)
    if not spec.volume_step.is_finite() or spec.volume_step <= 0:
        raise ValueError("broker volume step must be finite and positive")
    volume = ((plan.volume * review.volume_fraction / spec.volume_step)
              .to_integral_value(rounding=ROUND_FLOOR) * spec.volume_step)
    if volume < spec.volume_min or volume <= 0:
        return ContextDecision(risk.decision_id, "REDUCED_BELOW_MINIMUM", None, review.rationale)
    fraction = volume / plan.volume
    reduced = replace(plan, volume=volume, actual_risk_amount=plan.actual_risk_amount * fraction,
                      actual_risk_percent=plan.actual_risk_percent * fraction)
    return ContextDecision(risk.decision_id, "REDUCED", reduced, review.rationale)


class ContextStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with sqlite3.connect(path) as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS context_cache (
                input_hash TEXT PRIMARY KEY, response_json TEXT NOT NULL,
                provider TEXT NOT NULL, model TEXT NOT NULL, created_at_utc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS context_calls (
                id INTEGER PRIMARY KEY, input_hash TEXT NOT NULL, provider TEXT NOT NULL,
                model TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER,
                output_tokens INTEGER, reported_cost_usd TEXT, created_at_utc TEXT NOT NULL);
            """)

    def cached(self, key: str) -> tuple[str, str, str] | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT response_json, provider, model FROM context_cache "
                             "WHERE input_hash=?", (key,)).fetchone()
        return (str(row[0]), str(row[1]), str(row[2])) if row else None

    def record(self, key: str, provider: str, model: str, status: str, now: datetime,
               reply: ProviderReply | None, review: ReviewResponse | None = None) -> None:
        _require_utc(now, "now")
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO context_calls VALUES (NULL,?,?,?,?,?,?,?,?)", (
                key, provider, model, status, reply.input_tokens if reply else None,
                reply.output_tokens if reply else None,
                str(reply.reported_cost_usd) if reply and reply.reported_cost_usd is not None
                else None, now.isoformat(),
            ))
            if review is not None:
                db.execute("INSERT OR IGNORE INTO context_cache VALUES (?,?,?,?,?)",
                           (key, review.model_dump_json(), provider, model, now.isoformat()))

    def costs(self, start: datetime, end: datetime) -> Mapping[str, object]:
        _require_utc(start, "start")
        _require_utc(end, "end")
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT reported_cost_usd FROM context_calls "
                              "WHERE created_at_utc>=? AND created_at_utc<?",
                              (start.isoformat(), end.isoformat())).fetchall()
        known = [Decimal(row[0]) for row in rows if row[0] is not None]
        return {"attempts": len(rows), "known_cost_usd": str(sum(known, Decimal(0))),
                "unavailable_cost_attempts": len(rows) - len(known),
                "complete": len(rows) == len(known)}


class ContextReviewer:
    def __init__(self, config: ContextConfig, provider: ContextProvider, store: ContextStore,
                 sleep: Callable[[float], None] = time.sleep):
        self.config, self.provider, self.store, self.sleep = config, provider, store, sleep

    def review(self, risk: RiskDecision, spec: SymbolSpec, market: Mapping[str, Any],
               evidence: Mapping[str, str], now: datetime) -> ContextDecision:
        _require_utc(now, "now")
        plan = risk.permitted_position_plan
        if risk.status is not DecisionStatus.ELIGIBLE or plan is None:
            return ContextDecision(risk.decision_id, "DETERMINISTIC_BLOCK", None,
                                   "Layer 5 blocked this proposal.")
        fallback = ContextDecision(risk.decision_id, "UNAVAILABLE", plan,
                                   "Context unavailable; deterministic allowance unchanged.")
        if not self.config.enabled:
            return fallback
        prompt = self.config.prompt_file.read_text(encoding="utf-8")
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        payload = json.dumps({"risk_decision_id": risk.decision_id, "plan": asdict(plan),
                              "market": market, "evidence": evidence,
                              "response_schema": ReviewResponse.model_json_schema()},
                             default=str, sort_keys=True, allow_nan=False)
        chain = json.dumps([p.model_dump() for p in self.config.providers], sort_keys=True)
        key = hashlib.sha256(f"{prompt_hash}|{chain}|{payload}".encode()).hexdigest()
        cached = self.store.cached(key)
        if cached:
            review = ReviewResponse.model_validate_json(cached[0])
            if not set(review.evidence_ids) <= set(evidence):
                raise ValueError("cached review cites unavailable evidence")
            return replace(apply_review(risk, review, spec), provider=cached[1], model=cached[2],
                           prompt_hash=prompt_hash, input_hash=key, cached=True)
        for provider in self.config.providers:
            for attempt in range(self.config.attempts_per_provider):
                reply = None
                try:
                    reply = self.provider.complete(provider, prompt, payload)
                    review = ReviewResponse.model_validate_json(reply.content)
                    if not set(review.evidence_ids) <= set(evidence):
                        raise ValueError("unknown evidence")
                    result = apply_review(risk, review, spec)
                except (ProviderFailure, ValidationError, ValueError) as exc:
                    status = str(exc) if isinstance(exc, ProviderFailure) else "INVALID_REVIEW"
                    self.store.record(key, provider.name, provider.model, status, now, reply)
                    if attempt + 1 < self.config.attempts_per_provider:
                        self.sleep(self.config.retry_backoff_seconds * 2 ** attempt)
                    continue
                self.store.record(key, provider.name, reply.model, "VALID", now, reply, review)
                return replace(result, provider=provider.name, model=reply.model,
                               prompt_hash=prompt_hash, input_hash=key)
        logging.getLogger("forex.context").warning(
            "All configured context providers unavailable. Using deterministic allowance; "
            "check provider keys, model availability and network."
        )
        return replace(fallback, prompt_hash=prompt_hash, input_hash=key, alert_required=True)
