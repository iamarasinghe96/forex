"""Provider-neutral, research-only CSV history ingestion with durable provenance."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from forex.config import MarketDataConfig
from forex.domain import Candle, Timeframe
from forex.errors import OperatorError
from forex.market_data import detect_gaps
from forex.persistence import CandleStore


@dataclass(frozen=True)
class ImportProvenance:
    dataset: str
    provider: str
    symbol: str
    source_granularity: str
    price_type: str
    timezone: str
    spread_available: bool
    volume_semantics: str
    transformations: tuple[str, ...]
    earliest_utc: datetime
    latest_utc: datetime
    row_count: int
    imported_at_utc: datetime
    input_sha256: str
    h4_alignment: str


@dataclass(frozen=True)
class VerificationReport:
    symbol: str
    timeframe: str
    earliest_utc: datetime
    latest_utc: datetime
    candle_count: int
    approximate_years: float
    expected_weekend_gaps: int
    unexplained_gaps: int
    duplicate_timestamps: int
    non_monotonic_timestamps: int
    invalid_ohlc: int
    missing_required_fields: int


def _schema(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS history_imports (
        dataset TEXT NOT NULL, provider TEXT NOT NULL, symbol TEXT NOT NULL,
        source_granularity TEXT NOT NULL, price_type TEXT NOT NULL, timezone TEXT NOT NULL,
        spread_available INTEGER NOT NULL, volume_semantics TEXT NOT NULL,
        transformations_json TEXT NOT NULL, earliest_utc TEXT NOT NULL, latest_utc TEXT NOT NULL,
        row_count INTEGER NOT NULL, imported_at_utc TEXT NOT NULL, input_sha256 TEXT NOT NULL,
        h4_alignment TEXT NOT NULL, PRIMARY KEY(dataset, input_sha256, symbol))""")


def aggregate_h4(h1: list[Candle], alignment_hour_utc: int) -> list[Candle]:
    """Aggregate complete H1 groups to fixed UTC research H4 boundaries."""
    if alignment_hour_utc not in range(4):
        raise ValueError("H4 alignment hour must be 0, 1, 2, or 3 UTC")
    groups: dict[datetime, list[Candle]] = {}
    for candle in sorted(h1, key=lambda item: item.timestamp_utc):
        shifted = candle.timestamp_utc - timedelta(hours=alignment_hour_utc)
        boundary = shifted.replace(hour=(shifted.hour // 4) * 4, minute=0, second=0,
                                   microsecond=0) + timedelta(hours=alignment_hour_utc)
        groups.setdefault(boundary, []).append(candle)
    output: list[Candle] = []
    for boundary, bars in sorted(groups.items()):
        expected = [boundary + timedelta(hours=i) for i in range(4)]
        if [bar.timestamp_utc for bar in bars] != expected:
            continue  # never fill an incomplete interval
        output.append(Candle.from_values(
            bars[0].symbol, Timeframe.H4, boundary, bars[0].open,
            max(bar.high for bar in bars), min(bar.low for bar in bars), bars[-1].close,
            sum(bar.tick_volume for bar in bars),
            max(bar.spread for bar in bars), sum(bar.real_volume for bar in bars),
        ))
    return output


def import_csv(
    path: Path, database: Path, *, dataset: str, provider: str, symbol: str,
    source_timezone: Literal["UTC"], price_type: str, spread_available: bool,
    volume_semantics: str, h4_alignment_hour_utc: int, imported_at: datetime | None = None,
) -> ImportProvenance:
    """Import strict H1 CSV (timestamp,open,high,low,close[,volume,spread]) atomically."""
    if source_timezone != "UTC":
        raise OperatorError("CSV import currently accepts only an explicit UTC source timezone.")
    raw = path.read_bytes()
    candles: list[Candle] = []
    seen: set[datetime] = set()
    try:
        rows = csv.DictReader(raw.decode("utf-8-sig").splitlines())
        required = {"timestamp", "open", "high", "low", "close"}
        if rows.fieldnames is None or not required.issubset(rows.fieldnames):
            raise ValueError(f"required columns are {sorted(required)}")
        for number, row in enumerate(rows, 2):
            timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
                raise ValueError(f"row {number} timestamp must be timezone-aware UTC")
            timestamp = timestamp.astimezone(UTC)
            if timestamp in seen:
                raise ValueError(f"duplicate timestamp at row {number}: {timestamp.isoformat()}")
            seen.add(timestamp)
            candles.append(Candle.from_values(
                symbol.upper(), Timeframe.H1, timestamp, row["open"], row["high"], row["low"],
                row["close"], row.get("volume") or 0, row.get("spread") or 0, 0,
            ))
    except (UnicodeError, KeyError, TypeError, ValueError) as exc:
        raise OperatorError(f"Invalid historical CSV {path}: {exc}; nothing was imported.") from exc
    if not candles:
        raise OperatorError(f"Historical CSV {path} contains no data rows.")
    if any(b.timestamp_utc <= a.timestamp_utc for a, b in zip(candles, candles[1:])):
        raise OperatorError("Historical CSV timestamps must be strictly increasing.")
    h4 = aggregate_h4(candles, h4_alignment_hour_utc)
    if not h4:
        raise OperatorError("Historical CSV cannot form any complete aligned H4 candle.")
    store = CandleStore(database)
    # External research databases are homogeneous: overlaps must be byte-for-byte equivalent.
    for timeframe, incoming in ((Timeframe.H1, candles), (Timeframe.H4, h4)):
        existing = {c.timestamp_utc: c for c in store.load(symbol, timeframe)}
        conflict = next((c for c in incoming if c.timestamp_utc in existing and existing[c.timestamp_utc] != c), None)
        if conflict:
            raise OperatorError(
                f"Conflicting {timeframe.value} overlap at {conflict.timestamp_utc.isoformat()}; "
                "research data was not modified. Use a separate dataset database."
            )
    imported = (imported_at or datetime.now(UTC)).astimezone(UTC)
    provenance = ImportProvenance(
        dataset, provider, symbol.upper(), "H1", price_type, "UTC", spread_available,
        volume_semantics, ("strict UTC normalization", "H4 deterministic OHLC from complete H1 groups"),
        candles[0].timestamp_utc, candles[-1].timestamp_utc, len(candles), imported,
        hashlib.sha256(raw).hexdigest(), f"fixed UTC boundary hour {h4_alignment_hour_utc}",
    )
    store.upsert(candles)
    store.upsert(h4)
    with sqlite3.connect(database) as connection:
        _schema(connection)
        values = asdict(provenance)
        connection.execute(
            "INSERT OR IGNORE INTO history_imports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (values["dataset"], values["provider"], values["symbol"], values["source_granularity"],
             values["price_type"], values["timezone"], int(values["spread_available"]),
             values["volume_semantics"], json.dumps(values["transformations"]),
             provenance.earliest_utc.isoformat(), provenance.latest_utc.isoformat(),
             provenance.row_count, provenance.imported_at_utc.isoformat(), provenance.input_sha256,
             provenance.h4_alignment),
        )
    return provenance


def verify_database(database: Path, symbols: list[str], config: MarketDataConfig) -> list[VerificationReport]:
    store = CandleStore(database)
    reports = []
    for symbol in symbols:
        for timeframe in Timeframe:
            candles = store.load(symbol, timeframe)
            if not candles:
                raise OperatorError(f"Research dataset has no {symbol} {timeframe.value} candles.")
            gaps = detect_gaps(candles, config)
            span = (candles[-1].timestamp_utc - candles[0].timestamp_utc).total_seconds()
            reports.append(VerificationReport(
                symbol, timeframe.value, candles[0].timestamp_utc, candles[-1].timestamp_utc,
                len(candles), span / (365.2425 * 86400), gaps.expected_weekend_gaps,
                len(gaps.unexplained_gaps), 0, 0, 0, 0,
            ))
    return reports
