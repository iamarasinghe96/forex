from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from test_paper import setup
from test_risk import NOW, spec

from forex.context import ContextDecision, ProviderReply
from forex.domain import Tick
from forex.journal import JournalStore
from forex.learning import (
    BucketScore,
    LearningStore,
    apply_overlay,
    merge_overlay,
    overlay_path,
    parse_patch,
    scale_plan,
    sizing_decision,
)
from forex.learning_worker import LearningWorker
from forex.notifications import NotificationWorker
from forex.telegram_commands import CommandHandler, TelegramCommandWorker

PATCH = """Looking at the scoreboard, USDJPY is carrying results. I suggest a slower trend filter.
```json
{"forex_patch": 1, "summary": "Slow the trend measure back to 15 bars",
 "analysis": {"trend_efficiency_window": 15}, "risk": {"risk_percent_per_trade": 2},
 "research_requests": ["Add a 3-12 month momentum filter"]}
```"""


def runtime_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, Any]:
    from test_analysis import candles, compact_config
    from test_risk import candidate

    from forex.analysis import AnalysisResult, analyse_market
    from forex.config import load_config
    from forex.context import ContextReviewer, ContextStore
    from forex.domain import Timeframe
    from forex.runtime import PaperRuntime

    paper, feed = setup(tmp_path)
    config = load_config(Path("config.yaml"))
    config.analysis = compact_config()
    config.broker.symbols = ["EURUSD"]
    config.context.enabled = False
    config.execution.session_rollover = None
    config.execution.session_rollover_hour_utc = 0
    config.paper.heartbeat_file = tmp_path / "heartbeat.json"
    config.paper.halt_file = tmp_path / "HALT"
    series = {frame: candles(frame, [1.1] * 60, start=NOW - frame.duration * 60) for frame in Timeframe}
    feed.candles.side_effect = lambda symbol, frame, start, end: series[frame]
    snapshot = analyse_market("EURUSD", series[Timeframe.H1], series[Timeframe.H4], NOW, config.analysis).snapshot
    fixture = replace(candidate(), candidate_id=snapshot.evaluation_id, evaluation_id=snapshot.evaluation_id)
    monkeypatch.setattr("forex.runtime.analyse_market", lambda *args: AnalysisResult(snapshot, fixture))
    runtime = PaperRuntime(config, feed, paper, ContextReviewer(config.context, Mock(), ContextStore(paper.path)),
                           lambda: NOW)
    return runtime, paper, feed


def test_closed_trade_is_scored_explained_and_forwarded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, paper, feed = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()
    assert len(paper.positions()) == 1
    assert any(e.kind == "learning_decision" for e in runtime.journal.events(limit=500))
    feed.tick.return_value = Tick("EURUSD", Decimal("1.085"), Decimal("1.0851"), NOW)  # Below the stop.
    paper.manage(NOW)
    paper.journal_fills(runtime.journal)
    provider = Mock()
    provider.complete.return_value = ProviderReply(json.dumps({
        "summary": "The uptrend stalled and reversed through the swing low.", "likely_causes": ["reversal"],
        "lesson": "One loss; watch late entries.", "category": "reversal"}), "model")
    worker = LearningWorker(lambda: runtime.config, runtime.journal, runtime.learning, provider,
                            lambda symbol: [], lambda: NOW)
    assert worker.once() == 1
    assert worker.once() == 0  # Cursor: each trade is learned once.
    scores = runtime.learning.scores(20)
    assert scores["pair:EURUSD"].trades == 1 and scores["pair:EURUSD"].total_r == pytest.approx(-1.5)
    assert scores["regime:TREND_UP"].losses == 1
    review = next(e for e in runtime.journal.events(limit=500) if e.kind == "trade_review")
    assert "LOSS -1.50 R" in review.payload["message"] and "stalled" in review.payload["message"]
    sender = Mock()
    NotificationWorker(runtime.journal, sender).once()
    assert any("Trade review: EURUSD LONG LOSS" in call.args[0] for call in sender.send.call_args_list)


def test_unavailable_ai_still_scores_the_trade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, paper, feed = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()
    feed.tick.return_value = Tick("EURUSD", Decimal("1.13"), Decimal("1.1301"), NOW)
    paper.manage(NOW, flatten=True)  # Closed in profit (+3R) by the operator halt.
    paper.journal_fills(runtime.journal)
    worker = LearningWorker(lambda: runtime.config, runtime.journal, runtime.learning, None, lambda s: [], lambda: NOW)
    worker.once()
    assert runtime.learning.scores(20)["all"].wins == 1
    assert runtime.learning.recent_reviews(1)[0]["review"]["source"] == "rule"


def test_sizing_needs_evidence_and_never_scales_up() -> None:
    def bucket(name: str, trades: int, total: float) -> BucketScore:
        return BucketScore(name, trades, 0, 0, total, total / (trades + 20), trades / (trades + 20))
    keys = ["all", "pair:EURUSD"]
    few = sizing_decision({"all": bucket("all", 5, -4)}, keys, min_trades=10, min_factor=0.25, skip_below_r=None)
    assert few.factor == 1 and not few.skip
    good = sizing_decision({"all": bucket("all", 40, 20)}, keys, min_trades=10, min_factor=0.25, skip_below_r=None)
    assert good.factor == 1  # Configured risk is the ceiling.
    weak = sizing_decision({"all": bucket("all", 40, -6)}, keys, min_trades=10, min_factor=0.25, skip_below_r=None)
    assert weak.factor == pytest.approx(1 + 2 * (-6 / 60))
    awful = sizing_decision({"all": bucket("all", 40, -30)}, keys, min_trades=10, min_factor=0.25, skip_below_r=-0.3)
    assert awful.skip


def test_scale_plan_reduces_volume_but_keeps_a_tradable_minimum() -> None:
    from test_risk import POLICY, account, candidate

    from forex.risk import DailyRiskState, PortfolioRiskState, decide_risk
    decision = decide_risk(candidate(), account(), spec(), Decimal("1.10"), Decimal("1.09"), None,
                           PortfolioRiskState(()), DailyRiskState("d", Decimal(10000), Decimal(10000)), POLICY)
    approved = ContextDecision(decision.decision_id, "APPROVED", decision.permitted_position_plan, "ok")
    assert approved.plan is not None
    half = scale_plan(approved, 0.5, spec())
    assert half.plan.volume == Decimal("0.17")  # 0.35 x 0.5 rounded down to the 0.01 step.
    assert half.plan.actual_risk_amount < approved.plan.actual_risk_amount
    assert scale_plan(approved, 1.0, spec()) is approved
    tiny = scale_plan(approved, 0.0001, spec())
    assert tiny.plan.volume == Decimal(".01")


def test_patch_parsing_rejects_anything_outside_the_whitelist() -> None:
    patch = parse_patch(PATCH)
    assert patch.changes() == {"analysis": {"trend_efficiency_window": 15}, "risk": {"risk_percent_per_trade": 2}}
    assert patch.research_requests == ["Add a 3-12 month momentum filter"]
    for bad in ('{"forex_patch": 1, "summary": "x", "execution": {"demo_enabled": true}}',
                '{"forex_patch": 1, "summary": "x", "risk": {"risk_percent_per_trade": 50}}',
                '{"forex_patch": 1, "summary": "x", "analysis": {"code": "import os"}}',
                '{"summary": "no marker"}', "no json at all"):
        with pytest.raises(ValueError):
            parse_patch(bad)


def test_overlay_applies_on_top_of_config_and_merges_patches() -> None:
    from forex.config import load_config
    base = load_config(Path("config.yaml"))
    overlay = merge_overlay({}, parse_patch(PATCH))
    overlay = merge_overlay(overlay, parse_patch('{"forex_patch": 1, "summary": "pause GBP", '
                                                 '"disabled_pairs": ["GBPUSD"], "exits": {"atr_trailing_multiple": null}}'))
    effective = apply_overlay(base, overlay)
    assert effective.analysis.trend_efficiency_window == 15
    assert effective.risk.conviction_risk_percent == {"low": 2, "medium": 2, "high": 2}
    assert effective.learning.disabled_pairs == ["GBPUSD"]
    assert effective.paper.atr_trailing_multiple is None
    assert effective.execution.demo_enabled is False and base.analysis.trend_efficiency_window == 10


def test_telegram_change_set_needs_approval_and_can_be_rolled_back(tmp_path: Path) -> None:
    from forex.config import load_config
    store = LearningStore(tmp_path / "paper.sqlite3")
    path = overlay_path(tmp_path / "paper.sqlite3")
    handler = CommandHandler(load_config(Path("config.yaml")), store, path, lambda: NOW)
    proposal = handler.handle(PATCH)[0].text
    assert "Change set #1" in proposal and "analysis.trend_efficiency_window: 10 -> 15" in proposal
    assert "Add a 3-12 month momentum filter" in proposal and not path.exists()
    assert "not pending" in handler.handle("/approve 9")[0].text
    assert "Approved #1" in handler.handle("/approve 1")[0].text
    assert json.loads(path.read_text())["analysis"]["trend_efficiency_window"] == 15
    assert "not pending" in handler.handle("/approve 1")[0].text
    assert "Rolled back #1" in handler.handle("/rollback")[0].text
    assert json.loads(path.read_text()) == {}
    handler.handle(PATCH)
    assert "Rejected #2" in handler.handle("/reject 2")[0].text
    bad = handler.handle('{"forex_patch": 1, "summary": "x", "disabled_pairs": ["AUDUSD"]}')[0].text
    assert bad.startswith("Not accepted")
    review = handler.handle("/review")[0]
    assert review.document is not None and "## Scoreboard" in review.document[1]
    assert "forex_patch" in review.document[1] and "No closed trades under these settings yet" in review.document[1]
    assert "No closed trades" in handler.handle("/scores")[0].text


class FakeTelegram:
    def __init__(self, updates: list[dict[str, Any]]):
        self.updates, self.sent = updates, []

    def post(self, url: str, **kwargs: Any) -> Any:
        method = url.rsplit("/", 1)[1]
        response = Mock()
        if method == "getUpdates":
            response.json.return_value = {"result": self.updates}
            self.updates = []
        else:
            self.sent.append((method, kwargs))
            response.json.return_value = {"result": True}
        return response


def test_only_the_operator_chat_can_command_the_bot(tmp_path: Path) -> None:
    from forex.config import load_config
    store = LearningStore(tmp_path / "paper.sqlite3")
    handler = CommandHandler(load_config(Path("config.yaml")), store, overlay_path(tmp_path / "paper.sqlite3"), lambda: NOW)
    client = FakeTelegram([
        {"update_id": 5, "message": {"chat": {"id": 999}, "text": PATCH}},
        {"update_id": 6, "message": {"chat": {"id": 42}, "text": "/review"}},
    ])
    worker = TelegramCommandWorker(handler, "token", "42", store, client)  # type: ignore[arg-type]
    assert worker.once() == 1
    assert store.patch(1) is None  # The stranger's change set was ignored.
    assert client.sent[0][0] == "sendDocument" and client.sent[0][1]["data"]["chat_id"] == "42"
    assert store.telegram_offset() == 6


def test_runtime_reloads_approved_settings_and_keeps_them_on_bad_files(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, _, _ = runtime_fixture(tmp_path, monkeypatch)
    runtime.next_analysis = NOW + timedelta(hours=1)
    runtime.overlay_path.write_text(json.dumps({"analysis": {"setup_score_threshold": 0.6},
                                                "risk": {"risk_percent_per_trade": 1}}))
    runtime.cycle()
    assert runtime.config.analysis.setup_score_threshold == 0.6
    assert runtime.policy.low_risk_percent == Decimal("0.01")
    updated = [e for e in runtime.journal.events(limit=500) if e.kind == "strategy_updated"]
    assert updated and "setup_score_threshold" in updated[0].payload["message"]
    runtime.overlay_path.write_text("{not json")
    runtime.cycle()
    assert runtime.config.analysis.setup_score_threshold == 0.6
    assert any("invalid" in e.payload.get("reason", "") for e in runtime.journal.events(limit=500) if e.kind == "alert")


def test_disabled_pair_is_not_evaluated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, paper, _ = runtime_fixture(tmp_path, monkeypatch)
    runtime.overlay_path.write_text(json.dumps({"disabled_pairs": ["EURUSD"]}))
    runtime.cycle()
    assert not paper.positions()
    assert not [e for e in JournalStore(paper.path).events(limit=500) if e.kind in {"candidate", "no_trade"}]


def test_broker_symbol_suffix_maps_to_the_plain_pair_bucket() -> None:
    from forex.learning import trade_facts
    candidate = {"side": "SHORT", "setup_type": "TREND_CONTINUATION_BREAKOUT_PULLBACK",
                 "h4_regime": {"label": "TREND_DOWN"}, "trade_style": "SWING",
                 "session_context": ["LONDON"], "volatility_context": 0.9}
    payload = {"symbol": "USDJPY.a", "entry": "150.00", "exit": "149.00", "reason": "STOP", "pnl_aud": "12",
               "opened_at_utc": NOW.isoformat(), "closed_at_utc": NOW.isoformat(),
               "intent": {"stop": "150.50", "side": "SHORT"},
               "decision_provenance": {"candidate": {"candidate": candidate}}}
    facts = trade_facts("t1", payload)
    assert facts is not None and facts.symbol == "USDJPY" and facts.r == pytest.approx(2.0)
    assert "pair_regime:USDJPY|TREND_DOWN" in facts.buckets() and "volatility:HIGH" in facts.buckets()
    assert trade_facts("t2", {"symbol": "EURUSD"}) is None  # No provenance: not scored.


def test_only_one_open_trade_per_pair_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime, paper, _ = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()
    assert len(paper.positions()) == 1
    runtime.store = Mock(claim=Mock(return_value=True), complete=Mock())  # Same signal again next hour.
    runtime.next_analysis = NOW
    runtime.cycle()
    assert len(paper.positions()) == 1
    assert any("Already holding 1 EURUSD" in e.payload.get("reason", "")
               for e in runtime.journal.events(limit=500) if e.kind == "no_trade")


def test_daily_summary_message_is_readable(tmp_path: Path) -> None:
    journal = JournalStore(tmp_path / "j.sqlite3")
    journal.append("PAPER", "daily_summary", "2026-10-01", {"closed_trades": 2, "wins": 1, "losses": 1,
                                                              "realized_pnl_aud": "12.5"}, NOW)
    sender = Mock()
    NotificationWorker(journal, sender).once()
    assert sender.send.call_args.args[0] == "Daily summary 2026-10-01: 2 trades closed (1 won, 1 lost), P&L A$+12.50."
