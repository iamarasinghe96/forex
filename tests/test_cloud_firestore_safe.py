from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from forex.cloud_sync import FirestoreMirror, firestore_safe
from forex.journal import JournalStore


def nested_arrays(value: Any) -> bool:
    if isinstance(value, dict):
        return any(nested_arrays(v) for v in value.values())
    if isinstance(value, list):
        return any(isinstance(v, list) or nested_arrays(v) for v in value)
    return False


class FakeDocument:
    def __init__(self, path: tuple[str, ...]):
        self.path = path

    def collection(self, name: str) -> "FakeCollection":
        return FakeCollection(self.path + (name,))


class FakeCollection:
    def __init__(self, path: tuple[str, ...]):
        self.path = path

    def document(self, name: str) -> FakeDocument:
        return FakeDocument(self.path + (name,))


class FakeBatch:
    def __init__(self, written: dict[tuple[str, ...], Any]):
        self.written = written

    def set(self, document: FakeDocument, value: Any) -> None:
        self.written[document.path] = value

    def commit(self) -> None:
        pass


class FakeClient:
    def __init__(self) -> None:
        self.written: dict[tuple[str, ...], Any] = {}

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection((name,))

    def batch(self) -> FakeBatch:
        return FakeBatch(self.written)


def test_risk_exposure_pairs_are_written_without_arrays_inside_arrays(tmp_path: Path) -> None:
    now = datetime(2026, 9, 30, 1, 7, tzinfo=UTC)
    journal = JournalStore(tmp_path / "paper.sqlite3")
    event = journal.append("PAPER", "risk_decision", "fixture", {"risk": {"exposure": {
        "risk_by_symbol": (("USDJPY", Decimal("2.5")),),
        "usd_directional_risk": (("long", Decimal("2.5")), ("short", Decimal(0)))}}}, now)
    client = FakeClient()
    FirestoreMirror(client).write(event, {"event_count": 1}, {"event_count": 1})
    document = client.written[("modes", "PAPER", "events", event.event_id)]
    assert not nested_arrays(document)
    assert document["payload"]["risk"]["exposure"]["risk_by_symbol"] == [{"items": ["USDJPY", "2.5"]}]
    assert document["payload_hash"] == event.payload_hash  # Verification still uses the local hash.


def test_firestore_safe_leaves_flat_values_unchanged() -> None:
    value = {"a": [1, "x", {"b": [2, 3]}], "c": None}
    assert firestore_safe(value) == value
