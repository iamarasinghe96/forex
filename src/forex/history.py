"""Provider-neutral, research-only CSV history ingestion with durable provenance."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
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
    integrity_basis: str


@dataclass(frozen=True)
class ResearchDataset:
    dataset_id: str
    provider: str
    symbols: tuple[str, ...]
    input_sha256: tuple[str, ...]
    price_type: str
    timezone: str
    h4_alignment: str
    spread_available: bool
    volume_semantics: str
    coverage: dict[str, dict[str, str]]
    fingerprint: str
    data_classification: str = "EXTERNAL RESEARCH DATA — NOT IC MARKETS BROKER-NATIVE HISTORY"


PROVENANCE_SCHEMA = """CREATE TABLE IF NOT EXISTS history_imports (
    dataset TEXT NOT NULL, provider TEXT NOT NULL, symbol TEXT NOT NULL,
    source_granularity TEXT NOT NULL, price_type TEXT NOT NULL, timezone TEXT NOT NULL,
    spread_available INTEGER NOT NULL, volume_semantics TEXT NOT NULL,
    transformations_json TEXT NOT NULL, earliest_utc TEXT NOT NULL, latest_utc TEXT NOT NULL,
    row_count INTEGER NOT NULL, imported_at_utc TEXT NOT NULL, input_sha256 TEXT NOT NULL,
    h4_alignment TEXT NOT NULL, PRIMARY KEY(dataset, input_sha256, symbol))"""
MEMBERSHIP_SCHEMA = """CREATE TABLE IF NOT EXISTS history_import_candles (
    dataset TEXT NOT NULL, input_sha256 TEXT NOT NULL, symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL, timestamp_utc TEXT NOT NULL,
    PRIMARY KEY(dataset, input_sha256, symbol, timeframe, timestamp_utc),
    FOREIGN KEY(dataset, input_sha256, symbol)
        REFERENCES history_imports(dataset, input_sha256, symbol))"""

SEMANTIC_FIELDS = (
    "dataset", "provider", "source_granularity", "price_type", "timezone",
    "spread_available", "volume_semantics", "h4_alignment",
)


def _schema(connection: sqlite3.Connection) -> None:
    connection.execute(PROVENANCE_SCHEMA)
    connection.execute(MEMBERSHIP_SCHEMA)


def _from_row(row: sqlite3.Row) -> ImportProvenance:
    return ImportProvenance(
        row["dataset"], row["provider"], row["symbol"], row["source_granularity"],
        row["price_type"], row["timezone"], bool(row["spread_available"]),
        row["volume_semantics"], tuple(json.loads(row["transformations_json"])),
        datetime.fromisoformat(row["earliest_utc"]).astimezone(UTC),
        datetime.fromisoformat(row["latest_utc"]).astimezone(UTC), row["row_count"],
        datetime.fromisoformat(row["imported_at_utc"]).astimezone(UTC), row["input_sha256"],
        row["h4_alignment"],
    )


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
        if [bar.timestamp_utc for bar in bars] != [boundary + timedelta(hours=i) for i in range(4)]:
            continue
        output.append(Candle.from_values(
            bars[0].symbol, Timeframe.H4, boundary, bars[0].open,
            max(bar.high for bar in bars), min(bar.low for bar in bars), bars[-1].close,
            sum(bar.tick_volume for bar in bars), max(bar.spread for bar in bars),
            sum(bar.real_volume for bar in bars),
        ))
    return output


def _candle_values(candles: list[Candle]) -> list[tuple[object, ...]]:
    return [(c.symbol, c.timeframe.value, c.timestamp_utc.isoformat(), str(c.open), str(c.high),
             str(c.low), str(c.close), c.tick_volume, c.spread, c.real_volume) for c in candles]


def _insert_provenance(connection: sqlite3.Connection, value: ImportProvenance) -> None:
    connection.execute(
        "INSERT INTO history_imports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (value.dataset, value.provider, value.symbol, value.source_granularity, value.price_type,
         value.timezone, int(value.spread_available), value.volume_semantics,
         json.dumps(value.transformations), value.earliest_utc.isoformat(),
         value.latest_utc.isoformat(), value.row_count, value.imported_at_utc.isoformat(),
         value.input_sha256, value.h4_alignment),
    )


def _semantic_tuple(value: ImportProvenance) -> tuple[object, ...]:
    return tuple(getattr(value, field) for field in SEMANTIC_FIELDS)


def _identity_metadata(value: ImportProvenance) -> tuple[object, ...]:
    """All persisted identity metadata except the deliberately stable import timestamp."""
    return (
        value.dataset, value.provider, value.symbol, value.source_granularity, value.price_type,
        value.timezone, value.spread_available, value.volume_semantics, value.transformations,
        value.earliest_utc, value.latest_utc, value.row_count, value.input_sha256,
        value.h4_alignment,
    )


def import_csv(
    path: Path, database: Path, *, dataset: str, provider: str, symbol: str,
    source_timezone: Literal["UTC"], price_type: str, spread_available: bool,
    volume_semantics: str, h4_alignment_hour_utc: int, imported_at: datetime | None = None,
) -> ImportProvenance:
    """Validate then atomically commit H1, derived H4, and provenance."""
    if source_timezone != "UTC":
        raise OperatorError("CSV import currently accepts only an explicit UTC source timezone.")
    raw = path.read_bytes()
    candles: list[Candle] = []
    seen: set[datetime] = set()
    try:
        rows = csv.DictReader(raw.decode("utf-8-sig").splitlines())
        fields = set(rows.fieldnames or ())
        required = {"timestamp", "open", "high", "low", "close"}
        if not required.issubset(fields):
            raise ValueError(f"required columns are {sorted(required)}")
        if spread_available and "spread" not in fields:
            raise ValueError("spread_available requires a spread column")
        if volume_semantics != "unavailable" and "volume" not in fields:
            raise ValueError("observed volume semantics require a volume column")
        for number, row in enumerate(rows, 2):
            timestamp = datetime.fromisoformat(row["timestamp"])
            if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0):
                raise ValueError(f"row {number} timestamp must be timezone-aware UTC")
            timestamp = timestamp.astimezone(UTC)
            if timestamp in seen:
                raise ValueError(f"duplicate timestamp at row {number}: {timestamp.isoformat()}")
            seen.add(timestamp)
            if spread_available and not row.get("spread"):
                raise ValueError(f"row {number} is missing observed spread")
            if volume_semantics != "unavailable" and not row.get("volume"):
                raise ValueError(f"row {number} is missing observed volume")
            candles.append(Candle.from_values(
                symbol.upper(), Timeframe.H1, timestamp, row["open"], row["high"], row["low"],
                row["close"], row.get("volume") or 0, row.get("spread") or 0, 0,
            ))
    except (ArithmeticError, UnicodeError, KeyError, TypeError, ValueError) as exc:
        raise OperatorError(f"Invalid historical CSV {path}: {exc}; nothing was imported.") from exc
    if not candles:
        raise OperatorError(f"Historical CSV {path} contains no data rows.")
    if any(b.timestamp_utc <= a.timestamp_utc for a, b in pairwise(candles)):
        raise OperatorError("Historical CSV timestamps must be strictly increasing.")
    h4 = aggregate_h4(candles, h4_alignment_hour_utc)
    if not h4:
        raise OperatorError("Historical CSV cannot form any complete aligned H4 candle.")
    transformations = ["strict UTC normalization", "H4 deterministic OHLC from complete H1 groups"]
    if not spread_available:
        transformations.append("stored spread zero is an unavailable-value placeholder")
    if volume_semantics == "unavailable":
        transformations.append("stored volume zero is an unavailable-value placeholder")
    candidate = ImportProvenance(
        dataset, provider, symbol.upper(), "H1", price_type, "UTC", spread_available,
        volume_semantics, tuple(transformations), candles[0].timestamp_utc,
        candles[-1].timestamp_utc, len(candles), (imported_at or datetime.now(UTC)).astimezone(UTC),
        hashlib.sha256(raw).hexdigest(), f"fixed UTC boundary hour {h4_alignment_hour_utc}",
    )

    CandleStore(database)  # create canonical schema before the single import transaction
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        _schema(connection)
        connection.commit()
        existing_identity = connection.execute(
            "SELECT * FROM history_imports WHERE dataset=? AND input_sha256=? AND symbol=?",
            (candidate.dataset, candidate.input_sha256, candidate.symbol),
        ).fetchone()
        if existing_identity is not None:
            persisted = _from_row(existing_identity)
            if _identity_metadata(persisted) != _identity_metadata(candidate):
                raise OperatorError("Import identity already exists with conflicting provenance metadata.")
            return persisted
        existing_rows = connection.execute("SELECT * FROM history_imports").fetchall()
        if existing_rows:
            reference = _from_row(existing_rows[0])
            if _semantic_tuple(reference) != _semantic_tuple(candidate):
                differences = [field for field in SEMANTIC_FIELDS
                               if getattr(reference, field) != getattr(candidate, field)]
                raise OperatorError(
                    f"Incompatible research dataset semantics ({', '.join(differences)}); "
                    "use a separate research database."
                )
        for timeframe, incoming in ((Timeframe.H1, candles), (Timeframe.H4, h4)):
            stored = CandleStore(database).load(symbol, timeframe)
            by_time = {c.timestamp_utc: c for c in stored}
            conflict = next((c for c in incoming if c.timestamp_utc in by_time and by_time[c.timestamp_utc] != c), None)
            if conflict:
                raise OperatorError(
                    f"Conflicting {timeframe.value} overlap at {conflict.timestamp_utc.isoformat()}; "
                    "research data was not modified. Use a separate dataset database."
                )
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """INSERT INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol,timeframe,timestamp_utc) DO NOTHING""",
                _candle_values(candles) + _candle_values(h4),
            )
            _insert_provenance(connection, candidate)
            connection.executemany(
                "INSERT INTO history_import_candles VALUES (?,?,?,?,?)",
                [(candidate.dataset, candidate.input_sha256, candidate.symbol,
                  candle.timeframe.value, candle.timestamp_utc.isoformat())
                 for candle in candles + h4],
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return candidate


def validate_research_database(
    database: Path, symbols: list[str], config: MarketDataConfig,
) -> tuple[ResearchDataset, list[VerificationReport]]:
    """Establish provenance/storage invariants and return a deterministic identity."""
    store = CandleStore(database)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='history_imports'"
        ).fetchone()
        if table is None:
            raise OperatorError("Research database has candles but no provenance table.")
        provenance = [_from_row(row) for row in connection.execute(
            "SELECT * FROM history_imports ORDER BY dataset, symbol, input_sha256"
        )]
        memberships = connection.execute(
            "SELECT symbol, timeframe, timestamp_utc FROM history_import_candles"
        ).fetchall()
    if not provenance:
        raise OperatorError("Research database has no persisted import provenance.")
    reference = provenance[0]
    for item in provenance[1:]:
        if _semantic_tuple(item) != _semantic_tuple(reference):
            raise OperatorError("Research database contains incompatible/mixed provenance semantics.")
    requested = tuple(sorted(symbol.upper() for symbol in symbols))
    provenanced = {item.symbol for item in provenance}
    missing = set(requested) - provenanced
    if missing:
        raise OperatorError(f"Research symbols lack provenance: {', '.join(sorted(missing))}.")
    reports: list[VerificationReport] = []
    coverage: dict[str, dict[str, str]] = {}
    for symbol in requested:
        symbol_provenance = [item for item in provenance if item.symbol == symbol]
        h1 = store.load(symbol, Timeframe.H1)
        if not h1:
            raise OperatorError(f"Research dataset has no {symbol} H1 candles.")
        if (h1[0].timestamp_utc != min(item.earliest_utc for item in symbol_provenance)
                or h1[-1].timestamp_utc != max(item.latest_utc for item in symbol_provenance)):
            raise OperatorError(f"Stored {symbol} H1 coverage does not correspond to provenance.")
        coverage[symbol] = {"earliest_utc": h1[0].timestamp_utc.isoformat(),
                            "latest_utc": h1[-1].timestamp_utc.isoformat()}
        for timeframe in Timeframe:
            candles = store.load(symbol, timeframe)
            if not candles:
                raise OperatorError(f"Research dataset has no {symbol} {timeframe.value} candles.")
            stored_timestamps = {candle.timestamp_utc.isoformat() for candle in candles}
            provenanced_timestamps = {
                row["timestamp_utc"] for row in memberships
                if row["symbol"] == symbol and row["timeframe"] == timeframe.value
            }
            if stored_timestamps != provenanced_timestamps:
                raise OperatorError(
                    f"Stored {symbol} {timeframe.value} candles do not exactly match provenance."
                )
            gaps = detect_gaps(candles, config)
            span = (candles[-1].timestamp_utc - candles[0].timestamp_utc).total_seconds()
            reports.append(VerificationReport(
                symbol, timeframe.value, candles[0].timestamp_utc, candles[-1].timestamp_utc,
                len(candles), span / (365.2425 * 86400), gaps.expected_weekend_gaps,
                len(gaps.unexplained_gaps), 0, 0, 0, 0,
                "duplicates prevented by SQLite primary key; ordering and OHLC/null validity "
                "re-established while loading validated Candle objects",
            ))
    identity = {
        "dataset_id": reference.dataset, "provider": reference.provider, "symbols": requested,
        "input_sha256": tuple(item.input_sha256 for item in provenance if item.symbol in requested),
        "price_type": reference.price_type, "timezone": reference.timezone,
        "h4_alignment": reference.h4_alignment, "spread_available": reference.spread_available,
        "volume_semantics": reference.volume_semantics, "coverage": coverage,
    }
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ResearchDataset(
        reference.dataset, reference.provider, requested,
        tuple(item.input_sha256 for item in provenance if item.symbol in requested),
        reference.price_type, reference.timezone, reference.h4_alignment,
        reference.spread_available, reference.volume_semantics, coverage, fingerprint,
    ), reports


def verify_database(database: Path, symbols: list[str], config: MarketDataConfig) -> list[VerificationReport]:
    return validate_research_database(database, symbols, config)[1]
