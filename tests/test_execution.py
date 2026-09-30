from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_context import response, risk
from test_risk import NOW, POLICY, account, candidate, spec

from forex.context import ReviewResponse, apply_review
from forex.domain import Tick
from forex.execution import (
    BrokerEvidence,
    ExecutionService,
    ExecutionSnapshot,
    ExecutionStore,
    OrderIntent,
    SubmissionResult,
)
from forex.persistence import RiskSessionStore
from forex.risk import DailyRiskState


class FakeExecutionBroker:
    def __init__(self) -> None:
        self.calls: list[OrderIntent] = []
        self.fail_after_accept = False
        self.show_evidence = True
        self.quote_time = NOW
        self.ask = Decimal("1.10")

    def snapshot(self, symbol: str, now: object) -> ExecutionSnapshot:
        return ExecutionSnapshot(account(), spec(),
                                 Tick(symbol, Decimal("1.0999"), self.ask, self.quote_time),
                                 (), True, True, NOW)

    def submit(self, intent: OrderIntent) -> SubmissionResult:
        self.calls.append(intent)
        if self.fail_after_accept:
            raise ConnectionError("lost response")
        return SubmissionResult("ACCEPTED", "123", "fixture accepted")

    def evidence(self, start: object, end: object) -> tuple[BrokerEvidence, ...]:
        return tuple(BrokerEvidence(i.client_id, "123", "DEAL") for i in self.calls
                     if self.show_evidence)


def service(tmp_path: Path, broker: FakeExecutionBroker) -> ExecutionService:
    return ExecutionService(broker, ExecutionStore(tmp_path / "state.sqlite3"),
                            RiskSessionStore(tmp_path / "state.sqlite3"), POLICY, 1234, 30, 300)


def test_duplicate_identity_survives_restart_and_reconciliation(tmp_path: Path) -> None:
    broker = FakeExecutionBroker()
    first = service(tmp_path, broker)
    decision = risk()
    reviewed = apply_review(decision, ReviewResponse.model_validate_json(response()), spec())
    args = (candidate(), decision, reviewed, NOW, "day", Decimal(10000))
    accepted = first.execute(*args)
    assert accepted.state == "ACCEPTED" and len(broker.calls) == 1
    restarted = service(tmp_path, broker)
    assert restarted.execute(*args) == accepted
    assert restarted.reconcile(NOW - timedelta(days=1), NOW)[0].state == "RECONCILED"
    assert restarted.execute(*args).state == "RECONCILED"
    assert len(broker.calls) == 1


def test_lost_response_and_missing_history_never_resubmit(tmp_path: Path) -> None:
    broker = FakeExecutionBroker()
    broker.fail_after_accept = True
    broker.show_evidence = False
    runner = service(tmp_path, broker)
    decision = risk()
    reviewed = apply_review(decision, ReviewResponse.model_validate_json(response()), spec())
    args = (candidate(), decision, reviewed, NOW, "day", Decimal(10000))
    assert runner.execute(*args).state == "UNKNOWN"
    assert runner.reconcile(NOW - timedelta(days=1), NOW)[0].state == "UNKNOWN"
    assert runner.execute(*args).state == "UNKNOWN" and len(broker.calls) == 1
    broker.show_evidence = True
    assert runner.reconcile(NOW - timedelta(days=1), NOW)[0].state == "RECONCILED"


def test_stale_quote_and_daily_kill_are_rechecked_after_review(tmp_path: Path) -> None:
    broker = FakeExecutionBroker()
    runner = service(tmp_path, broker)
    decision = risk()
    reviewed = apply_review(decision, ReviewResponse.model_validate_json(response()), spec())
    broker.quote_time = NOW - timedelta(minutes=5)
    args = (candidate(), decision, reviewed, NOW, "day", Decimal(10000))
    assert runner.execute(*args).state == "BLOCKED"
    broker.quote_time = NOW
    runner.sessions.save(DailyRiskState("day", Decimal(10000), Decimal(10000),
                                        kill_switch_active=True), NOW)
    assert runner.execute(*args).state == "BLOCKED"
    assert not broker.calls


def test_price_change_cannot_increase_reviewed_money_risk(tmp_path: Path) -> None:
    broker = FakeExecutionBroker()
    broker.ask = Decimal("1.101")
    runner = service(tmp_path, broker)
    decision = risk()
    reviewed = apply_review(decision, ReviewResponse.model_validate_json(response()), spec())
    assert runner.execute(candidate(), decision, reviewed, NOW, "day", Decimal(10000)).state == "ACCEPTED"
    intent = broker.calls[0]
    assert reviewed.plan
    amount = (intent.entry - intent.stop) / spec().tick_size * spec().tick_value * intent.volume
    assert amount <= reviewed.plan.actual_risk_amount


def test_forged_review_cannot_bypass_ceiling(tmp_path: Path) -> None:
    broker = FakeExecutionBroker()
    runner = service(tmp_path, broker)
    decision = risk()
    reviewed = apply_review(decision, ReviewResponse.model_validate_json(response()), spec())
    assert reviewed.plan
    forged = replace(reviewed, plan=replace(reviewed.plan, volume=reviewed.plan.volume * 2))
    assert runner.execute(candidate(), decision, forged, NOW, "day", Decimal(10000)).state == "BLOCKED"
    assert not broker.calls


def test_atomic_reservation_blocks_different_inflight_candidate(tmp_path: Path) -> None:
    broker = FakeExecutionBroker()
    runner = service(tmp_path, broker)
    decision = risk()
    reviewed = apply_review(decision, ReviewResponse.model_validate_json(response()), spec())
    runner.execute(candidate(), decision, reviewed, NOW, "day", Decimal(10000))
    previous = broker.calls[0]
    assert not runner.store.reserve(replace(previous, client_id="fx-another"))


def test_equity_observation_preserves_kill_and_first_opening_balance(tmp_path: Path) -> None:
    sessions = RiskSessionStore(tmp_path / "sessions.sqlite3")
    sessions.save(DailyRiskState("day", Decimal(10000), Decimal(10000), kill_switch_active=True), NOW)
    observed = sessions.observe_equity("day", Decimal(100), Decimal(8700), POLICY, NOW)
    assert observed.kill_switch_active and observed.circuit_breaker_triggered
    assert observed.opening_balance == Decimal(10000)
    recovered = sessions.observe_equity("day", Decimal(500), Decimal(11000), POLICY, NOW)
    assert recovered.circuit_breaker_triggered and recovered.kill_switch_active


@pytest.mark.parametrize("days", [-1, 1])
def test_stale_or_future_candidate_cannot_submit(tmp_path: Path, days: int) -> None:
    broker = FakeExecutionBroker()
    runner = service(tmp_path, broker)
    decision = risk()
    reviewed = apply_review(decision, ReviewResponse.model_validate_json(response()), spec())
    changed = replace(candidate(), evaluation_time_utc=NOW + timedelta(days=days))
    assert runner.execute(changed, decision, reviewed, NOW, "day", Decimal(10000)).state == "BLOCKED"


@pytest.mark.parametrize("ask", ["1.10", "1.10001", "1.10050", "1.09990"])
def test_runtime_style_decision_survives_small_price_moves_during_review(tmp_path: Path, ask: str) -> None:
    from forex.risk import PortfolioRiskState, decide_risk

    # The paper runtime evaluates candidates with no requested objective (minimum 1.5R target).
    decision = decide_risk(candidate(), account(), spec(), Decimal("1.10"), Decimal("1.09"), None,
                           PortfolioRiskState(()), DailyRiskState("day", Decimal(10000), Decimal(10000)), POLICY)
    broker = FakeExecutionBroker()
    broker.ask = Decimal(ask)
    runner = service(tmp_path, broker)
    reviewed = apply_review(decision, ReviewResponse.model_validate_json(response()), spec())
    record = runner.execute(candidate(), decision, reviewed, NOW, "day", Decimal(10000))
    assert record.state == "ACCEPTED", record.detail
    intent = broker.calls[0]
    assert reviewed.plan
    loss = (intent.entry - intent.stop) / spec().tick_size * spec().tick_value * intent.volume
    assert loss <= reviewed.plan.actual_risk_amount
    assert (intent.target - intent.entry) / (intent.entry - intent.stop) >= POLICY.minimum_reward_risk


def test_runtime_requested_objective_sets_a_larger_paper_target(tmp_path: Path) -> None:
    from forex.risk import PortfolioRiskState, decide_risk

    # paper.target_reward_risk: 3R objective requested at evaluation time.
    decision = decide_risk(candidate(), account(), spec(), Decimal("1.10"), Decimal("1.09"), Decimal("1.13"),
                           PortfolioRiskState(()), DailyRiskState("day", Decimal(10000), Decimal(10000)), POLICY)
    broker = FakeExecutionBroker()
    broker.ask = Decimal("1.10")
    runner = service(tmp_path, broker)
    reviewed = apply_review(decision, ReviewResponse.model_validate_json(response()), spec())
    record = runner.execute(candidate(), decision, reviewed, NOW, "day", Decimal(10000))
    assert record.state == "ACCEPTED", record.detail
    assert broker.calls[0].target == Decimal("1.13")
