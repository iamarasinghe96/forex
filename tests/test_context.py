from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from test_risk import NOW, POLICY, account, candidate, spec

from forex.config import ContextConfig, ContextProviderConfig
from forex.context import (
    ContextReviewer,
    ContextSecrets,
    ContextStore,
    HTTPContextProvider,
    ProviderFailure,
    ProviderReply,
    ReviewResponse,
    apply_review,
)
from forex.risk import DailyRiskState, PortfolioRiskState, RiskDecision, decide_risk


def risk() -> RiskDecision:
    return decide_risk(candidate(), account(), spec(), Decimal("1.10"), Decimal("1.09"),
                       Decimal("1.12"), PortfolioRiskState(()),
                       DailyRiskState("test", Decimal(10000), Decimal(10000)), POLICY)


def response(verdict: str = "approve", fraction: str = "1") -> str:
    return json.dumps({"verdict": verdict, "volume_fraction": fraction,
                       "rationale": "Supplied evidence reviewed", "evidence_ids": ["e1"]})


class FakeProvider:
    def __init__(self, responses: list[str | Exception]):
        self.responses = responses
        self.calls: list[str] = []

    def complete(self, config: ContextProviderConfig, prompt: str, payload: str) -> ProviderReply:
        self.calls.append(config.name)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return ProviderReply(item, config.model, 20, 10, Decimal("0.001"))


def settings() -> ContextConfig:
    return ContextConfig(enabled=True, attempts_per_provider=1, retry_backoff_seconds=0,
                         providers=[ContextProviderConfig(name="groq", model="fixture-a"),
                                    ContextProviderConfig(name="gemini", model="fixture-b"),
                                    ContextProviderConfig(name="openrouter", model="fixture-c")])


@pytest.mark.parametrize("payload", [
    {"verdict": "approve", "volume_fraction": "1.01", "rationale": "x"},
    {"verdict": "approve", "volume_fraction": "1", "rationale": "x", "stop": 0},
    {"verdict": "reduce_size", "volume_fraction": "NaN", "rationale": "x"},
    {"verdict": "reject", "volume_fraction": "0", "rationale": "x"},
    {"verdict": "approve", "volume_fraction": "0.5", "rationale": "x"},
])
def test_schema_rejects_authority_expansion_and_unsupported_verdicts(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ReviewResponse.model_validate(payload)


def test_reduction_preserves_stop_objective_and_ceiling() -> None:
    original = risk()
    review = ReviewResponse.model_validate_json(response("reduce_size", ".333"))
    result = apply_review(original, review, spec())
    before, after = original.permitted_position_plan, result.plan
    assert before and after
    assert after.volume < before.volume
    assert after.volume % spec().volume_step == 0
    assert after.stop == before.stop and after.minimum_objective == before.minimum_objective
    assert after.actual_risk_amount <= before.actual_risk_amount
    assert apply_review(original, ReviewResponse.model_validate_json(response("reject", "0")),
                        spec()).plan is None


def test_failover_cache_and_attempt_costs(tmp_path: Path) -> None:
    provider = FakeProvider([ProviderFailure("HTTP_429"), "not JSON", response()])
    store = ContextStore(tmp_path / "db.sqlite3")
    reviewer = ContextReviewer(settings(), provider, store)
    first = reviewer.review(risk(), spec(), {"macro": "UNAVAILABLE"}, {"e1": "fact"}, NOW)
    assert first.status == "APPROVED" and first.provider == "openrouter"
    assert provider.calls == ["groq", "gemini", "openrouter"]
    again = reviewer.review(risk(), spec(), {"macro": "UNAVAILABLE"}, {"e1": "fact"}, NOW)
    assert again.cached and again.plan == first.plan
    assert len(provider.calls) == 3
    costs = store.costs(NOW, NOW + timedelta(days=1))
    assert costs["known_cost_usd"] == "0.002"
    assert costs["unavailable_cost_attempts"] == 1 and costs["complete"] is False


def test_unavailable_context_neutral_and_blocked_risk_never_calls_provider(tmp_path: Path) -> None:
    provider = FakeProvider([ProviderFailure("DOWN")] * 3)
    reviewer = ContextReviewer(settings(), provider, ContextStore(tmp_path / "db.sqlite3"))
    original = risk()
    result = reviewer.review(original, spec(), {}, {}, NOW)
    assert result.plan == original.permitted_position_plan and result.alert_required
    from forex.risk import DecisionStatus
    blocked = replace(original, status=DecisionStatus.HARD_RISK_BLOCK, permitted_position_plan=None)
    assert reviewer.review(blocked, spec(), {}, {}, NOW).plan is None
    assert len(provider.calls) == 3


def test_invented_evidence_fails_over_and_changed_payload_is_not_cached(tmp_path: Path) -> None:
    provider = FakeProvider([response("reject", "0"), response(), response()])
    reviewer = ContextReviewer(settings(), provider, ContextStore(tmp_path / "db.sqlite3"))
    first = reviewer.review(risk(), spec(), {"state": 1}, {"e2": "fact"}, NOW)
    # Even approval cannot cite invented evidence; all three responses are invalid.
    assert first.status == "UNAVAILABLE" and len(provider.calls) == 3
    provider.responses = [response(), response()]
    reviewer.review(risk(), spec(), {"state": 1}, {"e1": "fact"}, NOW)
    result = reviewer.review(risk(), spec(), {"state": 2}, {"e1": "fact"}, NOW)
    assert not result.cached and len(provider.calls) == 5


def test_http_adapter_never_leaks_provider_body_or_key() -> None:
    key = "fixture-secret"
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {key}"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(429, text=f"body includes {key}")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        adapter = HTTPContextProvider(settings(), ContextSecrets(groq_api_key=key), client)
        with pytest.raises(ProviderFailure, match="HTTP_429") as failure:
            adapter.complete(settings().providers[0], "prompt", "payload")
        assert key not in str(failure.value)


def test_disabled_context_never_calls_provider_and_tiny_reduction_never_rounds_up(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([])
    reviewer = ContextReviewer(ContextConfig(), provider, ContextStore(tmp_path / "db.sqlite3"))
    original = risk()
    assert reviewer.review(original, spec(), {}, {}, NOW).plan == original.permitted_position_plan
    assert provider.calls == []
    tiny = ReviewResponse.model_validate_json(response("reduce_size", "0.00001"))
    assert apply_review(original, tiny, spec()).status == "REDUCED_BELOW_MINIMUM"


def test_http_success_records_unknown_cost_without_inventing_prices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "model": "actual-model", "choices": [{"message": {"content": response()}}],
            "usage": {"prompt_tokens": 25, "completion_tokens": 12},
        })
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        reply = HTTPContextProvider(settings(), ContextSecrets(groq_api_key="fixture"), client).complete(
            settings().providers[0], "prompt", "payload")
    assert reply.model == "actual-model" and reply.input_tokens == 25
    assert reply.reported_cost_usd is None
