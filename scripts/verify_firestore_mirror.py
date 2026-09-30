"""Exercise the Python mirror against a local demo emulator only; never a real project."""

import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from google.auth.credentials import AnonymousCredentials
from google.cloud.firestore import Client

from forex.cloud_sync import FirestoreMirror, SyncWorker
from forex.journal import JournalStore

if os.environ.get("FIRESTORE_EMULATOR_HOST") != "127.0.0.1:8080":
    raise SystemExit("Start the local Firestore emulator on 127.0.0.1:8080; real projects are prohibited.")

client = Client(project="demo-forex-security", credentials=AnonymousCredentials())
now = datetime.now(UTC)
try:
    with TemporaryDirectory(prefix="forex-emulator-check-") as directory:
        root = Path(directory)
        journal = JournalStore(root / "fixture.sqlite3")
        event = journal.append("PAPER", "no_trade", "emulator-fixture", {"reason": "synthetic verification"}, now)
        mirror = FirestoreMirror(client)
        worker = SyncWorker(journal, mirror, 5, 60, root / "HALT")
        if worker.sync_once(now).delivered != 1:
            raise RuntimeError("Mirror delivery failed")
        if mirror.fingerprint("PAPER", event.event_id) != event.payload_hash:
            raise RuntimeError("Event fingerprint mismatch")
        client.collection("modes").document("PAPER").collection("aggregates").document("all").set({"bad": True})
        if worker.reconcile_page(now)[0] != 1 or worker.sync_once(now).delivered != 1:
            raise RuntimeError("Aggregate divergence repair failed")
        if not mirror.summary_matches("PAPER", "all", journal.summary("PAPER")):
            raise RuntimeError("Aggregate was not repaired")
        client.collection("controls").document("paper_halt").set({"mode": "PAPER", "active": True})
        worker.sync_once(now)
        if not (root / "HALT").is_file():
            raise RuntimeError("Remote emulator halt did not latch locally")
        print("LOCAL_EMULATOR_MIRROR_AGGREGATE_REPAIR_AND_HALT_VERIFIED; external project NOT_RUN")
finally:
    client.close()
