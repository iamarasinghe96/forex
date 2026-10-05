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
from forex.operations import SingleWriter
from forex.serialization import json_value


class CloudSecrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FOREX_", extra="ignore")
    firebase_service_account_file: Path | None = None


def configured_worker(config: CloudConfig, journal: JournalStore,
                      halt_file: Path | None = None) -> SyncWorker | None:
    if not config.enabled:
        return None
    if config.emergency_halt_enabled and halt_file is None:
        raise OperatorError("Remote paper halt requires an explicit local halt-file path.")
    secret_path = CloudSecrets().firebase_service_account_file
    if secret_path is None:
        raise OperatorError("Firebase credential path is missing. Set it in local .env; keep sync disabled until ready.")
    try:
        mirror = FirestoreMirror.configured(config.project_id, secret_path)
    except (ValueError, OSError, RuntimeError):
        raise OperatorError("Firebase initialization failed. Check the optional SDK, project and local credential file.") from None
    return SyncWorker(journal, mirror, config.retry_base_seconds, config.retry_maximum_seconds,
                      halt_file if config.emergency_halt_enabled else None)


class JournalMirror(Protocol):
    def write(self, event: JournalEvent, summary: Mapping[str, Any],
              daily: Mapping[str, Any]) -> None: ...
    def fingerprint(self, mode: str, event_id: str) -> str | None: ...
    def paper_halt_requested(self) -> bool: ...
    def summary_matches(self, mode: str, bucket: str, expected: Mapping[str, Any]) -> bool: ...


@dataclass(frozen=True)
class SyncResult:
    delivered: int
    failed: int


class SyncWorker:
    def __init__(self, journal: JournalStore, mirror: JournalMirror,
                 retry_base_seconds: float, retry_maximum_seconds: float,
                 halt_file: Path | None = None):
        if not 0 < retry_base_seconds <= retry_maximum_seconds:
            raise ValueError("sync retry limits must satisfy 0 < base <= maximum")
        self.journal, self.mirror = journal, mirror
        self.retry_base, self.retry_max = retry_base_seconds, retry_maximum_seconds
        self.halt_file = halt_file

    def sync_once(self, now: datetime, limit: int = 100) -> SyncResult:
        with SingleWriter(self.journal.path.with_suffix(".cloud-sync.lock")):
            return self._sync_once(now, limit)

    def _sync_once(self, now: datetime, limit: int) -> SyncResult:
        if self.halt_file is not None:
            try:
                if self.mirror.paper_halt_requested():
                    self.halt_file.parent.mkdir(parents=True, exist_ok=True)
                    self.halt_file.write_text("Remote authenticated admin requested PAPER halt/flatten. Local manual review required before clearing.", encoding="utf-8")
            except Exception:  # noqa: BLE001 - remote control outage cannot roll back local journal
                logging.getLogger("forex.controls").error("Remote paper halt poll failed; use the local halt procedure.")
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
        divergent_buckets: dict[tuple[str, str], bool] = {}
        for event in self.journal.events(after_sequence=after_sequence, limit=limit):
            for bucket in ("all", event.observed_at_utc.date().isoformat()):
                key = (event.mode, bucket)
                if key not in divergent_buckets:
                    divergent_buckets[key] = not self.mirror.summary_matches(
                        event.mode, bucket, self.journal.summary(event.mode, bucket))
            if (self.mirror.fingerprint(event.mode, event.event_id) != event.payload_hash or
                    divergent_buckets[(event.mode, "all")] or
                    divergent_buckets[(event.mode, event.observed_at_utc.date().isoformat())]):
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


def firestore_safe(value: Any) -> Any:
    """Firestore rejects an array directly inside an array (InvalidArgument). Wrap inner
    arrays as {"items": [...]}; the local journal and its payload hash stay unchanged."""
    if isinstance(value, dict):
        return {key: firestore_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [{"items": firestore_safe(item)} if isinstance(item, list) else firestore_safe(item)
                for item in value]
    return value


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
        batch.set(root.collection("events").document(event.event_id), firestore_safe(json_value(event)))
        batch.set(root.collection("aggregates").document("all"), dict(summary))
        batch.set(root.collection("aggregates").document(event.observed_at_utc.date().isoformat()),
                  dict(daily))
        if event.kind == "position_chart":  # The dashboard reads the latest chart from one document.
            batch.set(root.collection("aggregates").document("chart"),
                      firestore_safe(json_value({**event.payload, "sequence": event.sequence})))
        batch.commit()

    def fingerprint(self, mode: str, event_id: str) -> str | None:
        document = self.client.collection("modes").document(mode).collection("events").document(event_id).get()
        value = document.to_dict() if document.exists else None
        return str(value["payload_hash"]) if value and "payload_hash" in value else None

    def paper_halt_requested(self) -> bool:
        document = self.client.collection("controls").document("paper_halt").get(timeout=10)
        value = document.to_dict() if document.exists else None
        return bool(value and value.get("mode") == "PAPER" and value.get("active") is True)

    def summary_matches(self, mode: str, bucket: str, expected: Mapping[str, Any]) -> bool:
        document = self.client.collection("modes").document(mode).collection("aggregates").document(bucket).get()
        return bool(document.exists and document.to_dict() == json_value(expected))
