"""Operator commands over Telegram: scores, the Claude review prompt, and approving strategy patches.

Only messages from the configured operator chat are read. A pasted reply can change nothing but the
whitelisted, bounded settings in ``StrategyPatch``; it is stored as PENDING until ``/approve N``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any

import httpx

from forex.config import AppConfig
from forex.errors import OperatorError
from forex.learning import (
    PATCH_MARKER,
    LearningStore,
    apply_overlay,
    describe_changes,
    knobs,
    merge_overlay,
    parse_patch,
    read_overlay,
    review_prompt,
    strategy_version,
    write_overlay,
)

LOGGER = logging.getLogger("forex.telegram")
HELP = (
    "Forex paper bot commands:\n"
    "/scores - what the bot has learned so far\n"
    "/settings - settings a review may change\n"
    "/review - get the learning prompt to paste into Claude\n"
    "Paste Claude's JSON reply here - the bot checks it and shows the changes\n"
    "/approve N or /reject N - decide on change set N\n"
    "/rollback - undo the last approved change set"
)


@dataclass(frozen=True)
class Reply:
    text: str
    document: tuple[str, str] | None = None  # (file name, content)


class CommandHandler:
    def __init__(self, base: AppConfig, store: LearningStore, overlay: Path,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.base, self.store, self.overlay_path, self.clock = base, store, overlay, clock

    def effective(self, overlay: dict[str, Any] | None = None) -> AppConfig:
        return apply_overlay(self.base, read_overlay(self.overlay_path) if overlay is None else overlay)

    def handle(self, text: str) -> list[Reply]:
        command = text.strip().split(maxsplit=1)[0].lower() if text.strip() else ""
        argument = text.strip().split(maxsplit=1)[1] if len(text.strip().split(maxsplit=1)) > 1 else ""
        if PATCH_MARKER in text:
            return [self.propose(text)]
        if command in {"/start", "/help"}:
            return [Reply(HELP)]
        if command == "/scores":
            return [self.scores()]
        if command == "/settings":
            config = self.effective()
            flat = describe_changes(self.base, config)
            body = "\n".join(f"{k}: {v}" for k, v in knobs(config).items())
            return [Reply(f"Current settings, version {strategy_version(config)} (a review may change only these):\n"
                          + body
                          + ("\n\nChanged from config.yaml:\n" + "\n".join(flat) if flat else ""))]
        if command == "/review":
            instructions = self.base.learning.review_prompt_file.read_text(encoding="utf-8")
            prompt = review_prompt(self.effective(), self.store, instructions, self.clock())
            return [Reply("Open Claude, attach or paste this file, and send it. Then paste Claude's JSON reply "
                          "back here.", ("forex-learning-prompt.txt", prompt))]
        if command in {"/approve", "/reject"}:
            if not argument.strip().isdigit():
                return [Reply(f"Use {command} followed by the change-set number, e.g. {command} 3")]
            return [self.approve(int(argument)) if command == "/approve" else self.reject(int(argument))]
        if command == "/rollback":
            return [self.rollback()]
        return [Reply("I did not understand that. " + HELP)]

    def scores(self) -> Reply:
        config = self.effective()
        prior, version = config.learning.prior_trades, strategy_version(config)
        history = "\n".join(v.line() for v in self.store.versions())
        scores = sorted(self.store.scores(prior, version).values(), key=lambda b: (-b.trades, b.bucket))
        if not scores:
            return Reply(f"No closed trades under the current settings ({version}) yet. Scores appear after "
                         "the first trade closes." + (f"\n\nEarlier settings:\n{history}" if history else ""))
        best = sorted(scores, key=lambda b: -b.score_r)[:5]
        worst = sorted(scores, key=lambda b: b.score_r)[:5]
        return Reply(f"Settings {version}. Overall: " + scores[0].line()
                     + "\n\nStrongest:\n" + "\n".join(b.line() for b in best)
                     + "\n\nWeakest:\n" + "\n".join(b.line() for b in worst)
                     + "\n\nAll settings versions:\n" + history
                     + f"\n\navg ± one standard error. Score = total R / (trades + {prior}), evidence weight = "
                     f"trades / (trades + {prior}); neither is a probability of profit. Sizing shrinks only for "
                     f"buckets whose average + {config.learning.evidence_z:g} standard errors is below 0 R.")

    def propose(self, text: str) -> Reply:
        try:
            patch = parse_patch(text)
            current = read_overlay(self.overlay_path)
            proposed = merge_overlay(current, patch)
            before, after = self.effective(current), self.effective(proposed)
            unknown = set(patch.disabled_pairs or ()) - {s.upper() for s in self.base.broker.symbols}
            if unknown:
                raise ValueError(f"unknown pairs in disabled_pairs: {sorted(unknown)}")
        except (ValueError, OperatorError) as exc:
            return Reply(f"Not accepted: {exc}\nNothing was changed. Ask Claude to correct the JSON and paste it again.")
        changes = describe_changes(before, after)
        research = [f"- {item}" for item in patch.research_requests]
        if not changes:
            return Reply("This reply changes no settings, so there is nothing to approve."
                         + ("\nCode ideas to bring to Claude Code:\n" + "\n".join(research) if research else ""))
        patch_id = self.store.add_patch(patch, "\n".join(changes), self.clock())
        return Reply(f"Change set #{patch_id}: {patch.summary}\n\n" + "\n".join(changes)
                     + ("\n\nCode ideas (not applied; bring to Claude Code):\n" + "\n".join(research) if research else "")
                     + f"\n\nSend /approve {patch_id} to apply it, or /reject {patch_id}.")

    def approve(self, patch_id: int) -> Reply:
        found = self.store.patch(patch_id)
        if found is None or found[0] != "PENDING":
            return Reply(f"Change set #{patch_id} is not pending.")
        current = read_overlay(self.overlay_path)
        proposed = merge_overlay(current, found[1])
        try:
            self.effective(proposed)
        except (ValueError, OperatorError) as exc:
            return Reply(f"Change set #{patch_id} no longer validates ({exc}); nothing was changed.")
        write_overlay(self.overlay_path, proposed)
        self.store.decide(patch_id, "APPLIED", self.clock(), current, proposed)
        return Reply(f"Approved #{patch_id}. The bot loads it within a minute; signal settings take effect "
                     "at the next hourly evaluation. Send /rollback to undo.")

    def reject(self, patch_id: int) -> Reply:
        found = self.store.patch(patch_id)
        if found is None or found[0] != "PENDING":
            return Reply(f"Change set #{patch_id} is not pending.")
        self.store.decide(patch_id, "REJECTED", self.clock())
        return Reply(f"Rejected #{patch_id}. Nothing was changed.")

    def rollback(self) -> Reply:
        last = self.store.last_applied()
        if last is None:
            return Reply("No approved change set to roll back.")
        patch_id, before = last
        write_overlay(self.overlay_path, before)
        self.store.decide(patch_id, "ROLLED_BACK", self.clock(), None, before)
        return Reply(f"Rolled back #{patch_id}; the previous settings load within a minute.")


class TelegramCommandWorker:
    def __init__(self, handler: CommandHandler, token: str, chat_id: str, store: LearningStore,
                 client: httpx.Client | None = None):
        self.handler, self.chat_id, self.store = handler, str(chat_id), store
        self.base = f"https://api.telegram.org/bot{token}/"
        self.client = client or httpx.Client(timeout=40)

    def _call(self, method: str, **kwargs: Any) -> Any:
        try:
            response = self.client.post(self.base + method, **kwargs)
            response.raise_for_status()
            return response.json().get("result")
        except (httpx.HTTPError, ValueError):
            # Never log the exception: its URL contains the bot token.
            raise OperatorError(f"Telegram {method} failed") from None

    def send(self, reply: Reply) -> None:
        if reply.document is not None:
            name, content = reply.document
            self._call("sendDocument", data={"chat_id": self.chat_id, "caption": reply.text[:1000]},
                       files={"document": (name, content.encode("utf-8"), "text/plain")})
            return
        for start in range(0, len(reply.text), 4000):
            self._call("sendMessage", json={"chat_id": self.chat_id, "text": reply.text[start:start + 4000]})

    def once(self) -> int:
        offset = self.store.telegram_offset()
        updates = self._call("getUpdates", json={"offset": offset + 1 if offset else 0, "timeout": 25,
                                                 "allowed_updates": ["message"]}) or []
        handled = 0
        for update in updates:
            self.store.set_telegram_offset(int(update["update_id"]))
            message = update.get("message") or {}
            if str((message.get("chat") or {}).get("id")) != self.chat_id or not message.get("text"):
                continue  # Only the operator's own chat can command the bot.
            for reply in self.handler.handle(str(message["text"])):
                self.send(reply)
            handled += 1
        return handled

    def run(self, stop: Event) -> None:
        while not stop.is_set():
            try:
                self.once()
            except Exception as exc:  # noqa: BLE001 - commands must never interrupt trading
                LOGGER.warning("Telegram command polling failed (%s); retrying.", type(exc).__name__)
                stop.wait(15)
