"""Asynchronous cloud mirror; failures never roll back or block the local journal."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any, Protocol

from pydantic_settings import BaseSettings, SettingsConfigDict

from forex.config import CloudConfig
from forex.errors import OperatorError
from forex.journal import JournalEvent, JournalStore
from forex.serialization import json_value


class CloudSecrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FOREX_", extra="ignore")
    firebase_service_account_file: Path | None = None


def configured_worker(config: CloudConfig, journal: JournalStore) -> SyncWorker | None:
    if not config.enabled:
        return None
    secret_path = CloudSecrets().firebase_service_account_file
    if secret_path is None:
        raise OperatorError("Firebase credential path is missing. Set it in local .env; keep sync disabled until ready.")
    try:
        mirror = FirestoreMirror.configured(config.project_id, secret_path)
    except (ValueError, OSError, RuntimeError):
        raise OperatorError("Firebase initialization failed. Check the optional SDK, project and local credential file.") from None
    return SyncWorker(journal, mirror, config.retry_base_seconds, config.retry_maximum_seconds)


class JournalMirror(Protocol):
    def write(self, event: JournalEvent, summary: Mapping[str, Any],
              daily: Mapping[str, Any]) -> None: ...
    def fingerprint(self, mode: str, event_id: str) -> str | None: ...


@dataclass(frozen=True)
class SyncResult:
    delivered: int
    failed: int


class SyncWorker:
    def __init__(self, journal: JournalStore, mirror: JournalMirror,
                 retry_base_seconds: float, retry_maximum_seconds: float):
        if not 0 < retry_base_seconds <= retry_maximum_seconds:
            raise ValueError("sync retry limits must satisfy 0 < base <= maximum")
        self.journal, self.mirror = journal, mirror
        self.retry_base, self.retry_max = retry_base_seconds, retry_maximum_seconds

    def sync_once(self, now: datetime, limit: int = 100) -> SyncResult:
        delivered = failed = 0
        for event in self.journal.pending(now, limit):
            try:
                self.mirror.write(event, self.journal.summary(event.mode),
                                  self.journal.summary(event.mode, event.observed_at_utc.date().isoformat()))
            except Exception as exc:  # noqa: BLE001 - isolate all remote SDK failures from local trading
                self.journal.failed(event.event_id, now, type(exc).__name__,
                                    self.retry_base, self.retry_max)
                failed += 1
                continue
            self.journal.acknowledge(event.event_id, now)
            delivered += 1
        return SyncResult(delivered, failed)

    def reconcile_page(self, now: datetime, after_sequence: int = 0,
                       limit: int = 100) -> tuple[int, int]:
        repaired, cursor = 0, after_sequence
        for event in self.journal.events(after_sequence=after_sequence, limit=limit):
            if self.mirror.fingerprint(event.mode, event.event_id) != event.payload_hash:
                self.journal.requeue(event.event_id, now)
                repaired += 1
            cursor = event.sequence
        return repaired, cursor

    def run(self, stop: Event, clock: Callable[[], datetime], poll_seconds: float,
            batch_size: int) -> None:
        """Run on a separate worker thread/process; never on the decision call stack."""
        if poll_seconds <= 0 or batch_size <= 0:
            raise ValueError("worker polling and batch size must be positive")
        while not stop.is_set():
            try:
                self.sync_once(clock(), batch_size)
            except Exception as exc:  # noqa: BLE001 - surface local worker failure without killing decision loop
                logging.getLogger("forex.sync").error(
                    "Cloud worker %s; local records retained. Check database/network and restart sync.",
                    type(exc).__name__,
                )
            stop.wait(poll_seconds)


class FirestoreMirror:
    def __init__(self, client: Any):
        self.client = client

    @classmethod
    def configured(cls, project_id: str, service_account_file: Path) -> FirestoreMirror:
        """Initialize only when explicitly enabled; Admin credentials never enter browser payloads."""
        if not project_id or not service_account_file.is_file():
            raise ValueError("Configure Firebase project and local service-account path before sync")
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
        except ImportError:
            raise RuntimeError("Install the optional firebase dependency before enabling cloud sync") from None
        name = "forex-" + project_id
        try:
            app = firebase_admin.get_app(name)
        except ValueError:
            app = firebase_admin.initialize_app(credentials.Certificate(str(service_account_file)),
                                               {"projectId": project_id}, name=name)
        return cls(firestore.client(app=app))

    def write(self, event: JournalEvent, summary: Mapping[str, Any],
              daily: Mapping[str, Any]) -> None:
        root = self.client.collection("modes").document(event.mode)
        batch = self.client.batch()
        batch.set(root.collection("events").document(event.event_id), json_value(event))
        batch.set(root.collection("aggregates").document("all"), dict(summary))
        batch.set(root.collection("aggregates").document(event.observed_at_utc.date().isoformat()),
                  dict(daily))
        batch.commit()

    def fingerprint(self, mode: str, event_id: str) -> str | None:
        document = self.client.collection("modes").document(mode).collection("events").document(event_id).get()
        value = document.to_dict() if document.exists else None
        return str(value["payload_hash"]) if value and "payload_hash" in value else None
