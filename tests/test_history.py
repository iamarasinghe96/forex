from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from forex.backtest import history_gate
from forex.config import AnalysisConfig
from forex.domain import Candle, Timeframe
from forex.errors import OperatorError
from forex.history import aggregate_h4, import_csv
from forex.persistence import CandleStore


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
