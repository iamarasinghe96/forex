"""Research only: normalise dukascopy-node H1 bid CSVs for an additional history range.

Mirrors the original normalize_dukascopy.py checks (one raw file per pair, H1-aligned, strictly
increasing, unique timestamps, valid OHLC) and writes timestamp/open/high/low/close CSVs for
`forex import-history`. The original repaired 13 EURUSD candles from tick data; for this range a
candle whose close lies outside its own high/low is clamped to that range, every repair is
recorded in the manifest, and more than --max-repairs per pair aborts. Raw files are not modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

PAIRS = {"eurusd": "EURUSD", "gbpusd": "GBPUSD", "usdjpy": "USDJPY"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid(o: Decimal, h: Decimal, low: Decimal, c: Decimal) -> bool:
    return min(o, h, low, c) > 0 and low <= min(o, c) and h >= max(o, c) and h >= low


def normalise(source: Path, symbol: str, output: Path, max_repairs: int) -> dict[str, object]:
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or not {"timestamp", "open", "high", "low", "close"}.issubset(rows[0]):
        raise RuntimeError(f"{symbol}: raw CSV is empty or has unexpected columns")
    out, repairs, previous = [], [], None
    for line, row in enumerate(rows, start=2):
        epoch_ms = int(row["timestamp"])
        if epoch_ms % 3_600_000:
            raise RuntimeError(f"{symbol}: non-H1-aligned timestamp at line {line}")
        stamp = datetime.fromtimestamp(epoch_ms / 1000, UTC)
        if previous is not None and stamp <= previous:
            raise RuntimeError(f"{symbol}: timestamps not strictly increasing at line {line}")
        previous = stamp
        o, h, low, c = (Decimal(row[k]) for k in ("open", "high", "low", "close"))
        if not valid(o, h, low, c):
            clamped = min(max(c, low), h)
            if not valid(o, h, low, clamped):
                raise RuntimeError(f"{symbol}: unrepairable OHLC at {stamp.isoformat()} (line {line})")
            repairs.append({"timestamp_utc": stamp.isoformat(timespec="seconds"), "field": "close",
                            "original_value": row["close"], "corrected_value": str(clamped),
                            "policy": "clamped to the candle's own high/low"})
            close = str(clamped)
        else:
            close = row["close"]
        out.append({"timestamp": stamp.isoformat(timespec="seconds"), "open": row["open"],
                    "high": row["high"], "low": row["low"], "close": close})
    if len(repairs) > max_repairs:
        raise RuntimeError(f"{symbol}: {len(repairs)} invalid candles exceeds --max-repairs {max_repairs}; inspect the raw data")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "open", "high", "low", "close"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)
    print(f"{symbol}: rows {len(out):,} | {out[0]['timestamp']} -> {out[-1]['timestamp']} | repairs {len(repairs)} | {output}")
    return {"raw_filename": source.name, "raw_sha256": sha256(source), "normalized_filename": output.name,
            "normalized_sha256": sha256(output), "rows": len(out), "first_timestamp_utc": out[0]["timestamp"],
            "last_timestamp_utc": out[-1]["timestamp"], "repairs": repairs}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-repairs", type=int, default=50)
    args = parser.parse_args()
    manifest: dict[str, object] = {"provider": "Dukascopy datafeed", "acquisition_client": "dukascopy-node 1.50.0",
                                   "timeframe": "H1", "timezone": "UTC", "price_side": "bid",
                                   "generated_at_utc": datetime.now(UTC).isoformat(), "files": {}}
    for slug, symbol in PAIRS.items():
        matches = sorted(args.raw_dir.glob(f"{slug}-h1-bid-*.csv"))
        if len(matches) != 1:
            raise RuntimeError(f"{symbol}: expected exactly one raw H1 file in {args.raw_dir}, found {len(matches)}")
        manifest["files"][symbol] = normalise(matches[0], symbol, args.out_dir / f"{symbol}.csv", args.max_repairs)  # type: ignore[index]
    path = args.out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Manifest: {path}")


if __name__ == "__main__":
    main()
