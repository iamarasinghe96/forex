"""Background learning: score each closed paper trade and ask the AI provider why it won or lost."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from threading import Event
from typing import Any

from pydantic import ValidationError

from forex.config import AppConfig
from forex.context import ContextProvider, ProviderFailure
from forex.domain import Candle
from forex.journal import JournalStore
from forex.learning import (
    BucketScore,
    LearningStore,
    PostMortem,
    TradeFacts,
    postmortem_payload,
    price_path,
    trade_facts,
)

LOGGER = logging.getLogger("forex.learning")


class LearningWorker:
    def __init__(self, config: Callable[[], AppConfig], journal: JournalStore, store: LearningStore,
                 provider: ContextProvider | None, candles: Callable[[str], Sequence[Candle]],
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        # ``config`` is a callable so approved patches (e.g. prior_trades) apply without restart.
        self.config, self.journal, self.store = config, journal, store
        self.provider, self.candles, self.clock = provider, candles, clock

    def once(self) -> int:
        processed = 0
        for event in self.journal.events("PAPER", after_sequence=self.store.cursor(), limit=100):
            if event.kind == "trade_closed":
                self.learn(event.entity_id, event.payload)
                processed += 1
            self.store.set_cursor(event.sequence)
        return processed

    def learn(self, trade_id: str, payload: Mapping[str, Any]) -> None:
        facts = trade_facts(trade_id, payload)
        if facts is None:
            LOGGER.info("Closed trade %s has no decision provenance; not scored.", trade_id[:12])
            return
        now = self.clock()
        if not self.store.record_trade(facts, now):
            return
        config = self.config()
        scores = self.store.scores(config.learning.prior_trades, facts.strategy_version)
        review = self.explain(facts, scores, config)
        self.store.save_review(trade_id, review)
        outcome = "WIN" if facts.r > 0 else "LOSS" if facts.r < 0 else "BREAK-EVEN"
        pair = scores.get(f"pair_regime:{facts.symbol}|{facts.regime}")
        message = (f"Trade review: {facts.symbol} {facts.side} {outcome} {facts.r:+.2f} R "
                   f"({facts.exit_reason}, A${facts.pnl_aud:+.2f}). Why: {review.get('summary', '')} "
                   f"Lesson: {review.get('lesson', '')}"
                   + (f" Score {pair.bucket.split(':', 1)[1]} (settings {facts.strategy_version}): "
                      f"{pair.trades} trades, avg {pair.average_r:+.2f} ± {pair.std_error:.2f} R, "
                      f"evidence weight {pair.confidence:.0%}." if pair else ""))
        self.journal.append("PAPER", "trade_review", trade_id,
                            {"symbol": facts.symbol, "r": facts.r, "review": review, "message": message}, now)

    def explain(self, facts: TradeFacts, scores: Mapping[str, BucketScore], config: AppConfig) -> dict[str, Any]:
        """AI post-mortem; a short rule-based note if reviews are off or providers fail."""
        fallback = {"summary": f"Exited by {facts.exit_reason} at {facts.r:+.2f} R.",
                    "likely_causes": [], "lesson": "No AI review available; the score was still updated.",
                    "category": "other", "source": "rule"}
        if not config.learning.trade_reviews or self.provider is None or not config.context.providers:
            return fallback
        path = price_path(facts, self.candles(facts.symbol))
        prompt = config.learning.postmortem_prompt_file.read_text(encoding="utf-8")
        payload = postmortem_payload(facts, path, scores)
        for provider in config.context.providers:
            try:
                reply = self.provider.complete(provider, prompt, payload)
                review = PostMortem.model_validate_json(reply.content)
            except (ProviderFailure, ValidationError, ValueError):
                continue
            return {**review.model_dump(), "source": provider.name, "price_path": path}
        return {**fallback, "price_path": path}

    def run(self, stop: Event) -> None:
        while not stop.is_set():
            try:
                self.once()
            except Exception as exc:  # noqa: BLE001 - learning must never interrupt trading
                LOGGER.warning("Learning update failed (%s); it will retry.", type(exc).__name__)
            stop.wait(30)
