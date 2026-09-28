from __future__ import annotations

import sqlite3
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from forex.backtest import history_gate
from forex.config import AnalysisConfig
from forex.domain import Candle, Timeframe
from forex.errors import OperatorError
from forex.history import aggregate_h4, import_csv
from forex.history import validate_research_database
from forex.persistence import CandleStore
from forex.cli import verify_backtest


def candle(hour: int, *, day: int = 1) -> Candle:
    return Candle.from_values("EURUSD", Timeframe.H1, datetime(2020, 1, day, hour, tzinfo=UTC),
                              1, 3, 0.5, 2, 1, 0, 0)


def write_csv(path: Path, rows: list[str]) -> None:
    path.write_text("timestamp,open,high,low,close,volume\n" + "\n".join(rows) + "\n")


def test_h4_aggregation_is_deterministic_and_explicitly_aligned() -> None:
    bars = [candle(hour) for hour in range(1, 9)]
    result = aggregate_h4(bars, 1)
    assert [bar.timestamp_utc.hour for bar in result] == [1, 5]
    assert result[0].open == bars[0].open
    assert result[0].high == max(bar.high for bar in bars[:4])
    assert result[0].close == bars[3].close
    assert aggregate_h4(bars, 1) == result


def test_import_preserves_provenance_and_is_idempotent(tmp_path: Path) -> None:
    source, database = tmp_path / "data.csv", tmp_path / "research.sqlite3"
    write_csv(source, [f"2020-01-01T{hour:02}:00:00Z,1,2,0.5,1.5,10" for hour in range(8)])
    kwargs = dict(dataset="vendor-release", provider="verified-vendor", symbol="EURUSD",
                  source_timezone="UTC", price_type="midpoint", spread_available=False,
                  volume_semantics="tick count", h4_alignment_hour_utc=0,
                  imported_at=datetime(2026, 1, 1, tzinfo=UTC))
    first = import_csv(source, database, **kwargs)
    second = import_csv(source, database, **kwargs)
    assert first == second
    assert len(CandleStore(database).load("EURUSD", Timeframe.H1)) == 8
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT provider, price_type, timezone, spread_available, h4_alignment FROM history_imports").fetchone()
    assert row == ("verified-vendor", "midpoint", "UTC", 0, "fixed UTC boundary hour 0")


def test_import_rejects_naive_duplicate_invalid_ohlc_and_conflicting_overlap(tmp_path: Path) -> None:
    base = dict(database=tmp_path / "r.sqlite3", dataset="d", provider="p", symbol="EURUSD",
                source_timezone="UTC", price_type="bid", spread_available=False,
                volume_semantics="unavailable", h4_alignment_hour_utc=0)
    for name, rows in (
        ("naive", [f"2020-01-01T0{i}:00:00,1,2,.5,1.5,0" for i in range(4)]),
        ("duplicate", ["2020-01-01T00:00:00Z,1,2,.5,1.5,0"] * 4),
        ("ohlc", [f"2020-01-01T0{i}:00:00Z,1,1,.5,2,0" for i in range(4)]),
    ):
        path = tmp_path / f"{name}.csv"
        write_csv(path, rows)
        with pytest.raises(OperatorError):
            import_csv(path, **base)
    valid = tmp_path / "valid.csv"
    write_csv(valid, [f"2020-01-01T0{i}:00:00Z,1,2,.5,1.5,0" for i in range(4)])
    import_csv(valid, **base)
    write_csv(valid, [f"2020-01-01T0{i}:00:00Z,1,3,.5,1.5,0" for i in range(4)])
    with pytest.raises(OperatorError, match="Conflicting"):
        import_csv(valid, **base)


def test_five_year_gate_is_unchanged() -> None:
    start = datetime(2019, 1, 1, tzinfo=UTC)
    def series(timeframe: Timeframe, years: float) -> list[Candle]:
        return [Candle.from_values("EURUSD", timeframe, start, 1, 1, 1, 1, 0, 0, 0),
                Candle.from_values("EURUSD", timeframe, start + timedelta(days=365.2425 * years), 1, 1, 1, 1, 0, 0, 0)]
    assert not history_gate(series(Timeframe.H1, 4.99), series(Timeframe.H4, 6)).sufficient
    assert history_gate(series(Timeframe.H1, 5), series(Timeframe.H4, 5)).sufficient


def test_history_import_does_not_mutate_strategy_parameters() -> None:
    assert AnalysisConfig().model_dump() == AnalysisConfig().model_dump()


def test_atomic_failure_rolls_back_candles_and_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, database = tmp_path / "data.csv", tmp_path / "research.sqlite3"
    write_csv(source, [f"2020-01-01T0{i}:00:00Z,1,2,.5,1.5,0" for i in range(4)])
    monkeypatch.setattr("forex.history._insert_provenance",
                        lambda connection, value: (_ for _ in ()).throw(sqlite3.Error("boom")))
    with pytest.raises(sqlite3.Error, match="boom"):
        import_csv(source, database, dataset="d", provider="p", symbol="EURUSD",
                   source_timezone="UTC", price_type="bid", spread_available=False,
                   volume_semantics="unavailable", h4_alignment_hour_utc=0)
    assert CandleStore(database).load("EURUSD", Timeframe.H1) == []
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM history_imports").fetchone()[0] == 0


def test_reimport_returns_original_timestamp_and_rejects_changed_metadata(tmp_path: Path) -> None:
    source, database = tmp_path / "data.csv", tmp_path / "research.sqlite3"
    write_csv(source, [f"2020-01-01T0{i}:00:00Z,1,2,.5,1.5,0" for i in range(4)])
    kwargs = dict(dataset="d", provider="p", symbol="EURUSD", source_timezone="UTC",
                  price_type="bid", spread_available=False, volume_semantics="unavailable",
                  h4_alignment_hour_utc=0)
    original = import_csv(source, database, imported_at=datetime(2025, 1, 1, tzinfo=UTC), **kwargs)
    repeated = import_csv(source, database, imported_at=datetime(2026, 1, 1, tzinfo=UTC), **kwargs)
    assert repeated == original
    with pytest.raises(OperatorError, match="conflicting provenance"):
        import_csv(source, database, imported_at=datetime(2026, 1, 1, tzinfo=UTC),
                   **(kwargs | {"price_type": "ask"}))


@pytest.mark.parametrize("changed", [
    {"provider": "other"},
    {"h4_alignment_hour_utc": 1},
])
def test_database_rejects_incompatible_non_overlapping_feed(
    tmp_path: Path, changed: dict[str, object],
) -> None:
    database = tmp_path / "research.sqlite3"
    first, second = tmp_path / "one.csv", tmp_path / "two.csv"
    write_csv(first, [f"2020-01-01T0{i}:00:00Z,1,2,.5,1.5,0" for i in range(4)])
    hours = range(1, 5) if "h4_alignment_hour_utc" in changed else range(4)
    write_csv(second, [f"2021-01-01T{i:02}:00:00Z,1,2,.5,1.5,0" for i in hours])
    kwargs: dict[str, object] = dict(dataset="d", provider="p", symbol="EURUSD",
                                     source_timezone="UTC", price_type="bid",
                                     spread_available=False, volume_semantics="unavailable",
                                     h4_alignment_hour_utc=0)
    import_csv(first, database, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(OperatorError, match="Incompatible research dataset"):
        import_csv(second, database, **(kwargs | changed))  # type: ignore[arg-type]


@pytest.mark.parametrize(("spread", "volume", "message"), [
    (True, "unavailable", "spread column"),
    (False, "tick volume", "volume column"),
])
def test_claimed_observations_require_csv_columns(
    tmp_path: Path, spread: bool, volume: str, message: str,
) -> None:
    path = tmp_path / "data.csv"
    path.write_text("timestamp,open,high,low,close\n" + "\n".join(
        f"2020-01-01T0{i}:00:00Z,1,2,.5,1.5" for i in range(4)))
    with pytest.raises(OperatorError, match=message):
        import_csv(path, tmp_path / "r.sqlite3", dataset="d", provider="p", symbol="EURUSD",
                   source_timezone="UTC", price_type="bid", spread_available=spread,
                   volume_semantics=volume, h4_alignment_hour_utc=0)


def test_verify_rejects_candles_without_provenance(tmp_path: Path) -> None:
    database = tmp_path / "research.sqlite3"
    CandleStore(database).upsert([candle(hour) for hour in range(4)])
    from forex.config import MarketDataConfig
    with pytest.raises(OperatorError, match="no provenance table"):
        validate_research_database(database, ["EURUSD"], MarketDataConfig())
    with pytest.raises(OperatorError, match="no provenance table"):
        verify_backtest(Path("config.yaml"), database=database)


def test_research_report_is_fingerprinted_and_does_not_overwrite_native(
    tmp_path: Path,
) -> None:
    source, database = tmp_path / "data.csv", tmp_path / "research.sqlite3"
    rows = []
    start = datetime(2020, 1, 1, tzinfo=UTC)
    for index in range(300):
        rows.append(f"{(start + timedelta(hours=index)).isoformat()},1,2,.5,1.5,0")
    write_csv(source, rows)
    import_csv(source, database, dataset="release", provider="verified", symbol="EURUSD",
               source_timezone="UTC", price_type="midpoint", spread_available=False,
               volume_semantics="unavailable", h4_alignment_hour_utc=0)
    report_dir = tmp_path / "reports"
    config = tmp_path / "config.yaml"
    text = Path("config.yaml").read_text().replace(
        "symbols: [EURUSD, GBPUSD, USDJPY]", "symbols: [EURUSD]").replace(
        "report_directory: reports/backtest", f"report_directory: {report_dir}")
    config.write_text(text)
    native = report_dir / "strategy-baseline.json"
    native.parent.mkdir(parents=True)
    native.write_text("native")
    assert verify_backtest(config, database=database) == 0
    reports = list(report_dir.glob("research-baseline-*.json"))
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text())
    provenance = payload["research_dataset"]
    assert provenance["provider"] == "verified"
    assert provenance["dataset_id"] == "release"
    assert provenance["fingerprint"] in reports[0].name
    assert provenance["data_classification"].startswith("EXTERNAL RESEARCH DATA")
    assert native.read_text() == "native"
