"""One-off download of Dukascopy hourly bid prices (2012 to today) for the strategy lab.

The same pipeline as the original research data:
1. ``dukascopy-node`` 1.50.0 (run through Node's ``npx``) downloads one raw CSV per pair into
   ``data/history-raw/<from>_<to>/``; hours without trading ("flats") are left out;
2. ``scripts/normalize_dukascopy_range.py`` checks every row (hour-aligned, in order, valid prices;
   at most 50 repaired closes per pair) and writes ``data/history-normalized/<from>_<to>/``;
3. ``forex.history.import_csv`` imports H1, derives H4 and records provenance in
   ``data/dukascopy-history.sqlite3``.

A pair already downloaded is not fetched again, so an interrupted run can simply be restarted.
Existing databases are never changed.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from forex.history import import_csv

PAIRS = {"eurusd": "EURUSD", "gbpusd": "GBPUSD", "usdjpy": "USDJPY"}
CLIENT = "dukascopy-node@1.50.0"  # The client that fetched the original research data.
DATABASE = Path("data/dukascopy-history.sqlite3")
NORMALIZER = Path(__file__).resolve().parents[3] / "scripts" / "normalize_dukascopy_range.py"


def rows(database: Path, symbol: str) -> int:
    if not database.is_file():
        return 0
    with closing(sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='candles'").fetchone():
            return 0
        return int(db.execute("SELECT COUNT(*) FROM candles WHERE symbol=? AND timeframe='H1'",
                              (symbol,)).fetchone()[0])


def get_history(start: str = "2012-01-01", end: str | None = None) -> int:
    end = end or datetime.now(UTC).date().isoformat()
    if all(rows(DATABASE, s) for s in PAIRS.values()):
        print(f"{DATABASE} already holds all three pairs: "
              + ", ".join(f"{s} {rows(DATABASE, s):,} hours" for s in PAIRS.values()))
        return 0
    npx = shutil.which("npx")
    if npx is None:
        print("Node.js (npx) was not found. Install Node.js LTS from https://nodejs.org and run this again.")
        return 2
    run = f"{start}_{end}"
    raw, normalized = Path("data/history-raw") / run, Path("data/history-normalized") / run
    raw.mkdir(parents=True, exist_ok=True)
    for slug, symbol in PAIRS.items():
        if sorted(raw.glob(f"{slug}-h1-bid-*.csv")):
            print(f"{symbol}: already downloaded in {raw}")
            continue
        print(f"{symbol}: downloading hourly bid prices {start} to {end} from Dukascopy "
              "(several minutes per pair)...", flush=True)
        subprocess.run([npx, "--yes", CLIENT, "-i", slug, "-from", start, "-to", end, "-t", "h1", "-p", "bid",
                        "-f", "csv", "-dir", str(raw), "-r", "3"], check=True)
    print("Checking the downloaded prices...", flush=True)
    subprocess.run([sys.executable, str(NORMALIZER), "--raw-dir", str(raw), "--out-dir", str(normalized)], check=True)
    for symbol in PAIRS.values():
        result = import_csv(normalized / f"{symbol}.csv", DATABASE, dataset=f"dukascopy-h1-bid-{run}",
                            provider="Dukascopy (dukascopy-node 1.50.0)", symbol=symbol, source_timezone="UTC",
                            price_type="bid", spread_available=False, volume_semantics="unavailable",
                            h4_alignment_hour_utc=0, imported_at=datetime.now(UTC))
        print(f"{symbol}: imported ({result.dataset})", flush=True)
    print(f"\nDone: {DATABASE} - " + ", ".join(f"{s} {rows(DATABASE, s):,} hours" for s in PAIRS.values()))
    print("Next: double-click tools\\test-all-strategies.bat")
    return 0
