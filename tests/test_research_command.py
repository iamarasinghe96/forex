import json
from pathlib import Path

import pytest
from test_backtest import candle

from forex import cli
from forex.config import load_config
from forex.domain import Timeframe
from forex.history import ResearchDataset
from forex.persistence import CandleStore


def test_walk_forward_command_serializes_config_and_labels_limitations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_config(Path("config.yaml"))
    config.broker.symbols = ["EURUSD"]
    config.backtest.report_directory = tmp_path / "reports"
    config.logging.directory = tmp_path / "logs"
    dataset = ResearchDataset("synthetic", "test", ("EURUSD",), ("fixture",), "bid", "UTC",
                              "fixture", False, "unavailable", {}, "fixture")
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    monkeypatch.setattr(cli, "validate_research_database", lambda *args: (dataset, []))
    store = CandleStore(tmp_path / "fixture.sqlite3")
    store.upsert([candle(i) for i in range(5)] + [candle(0, Timeframe.H4)])
    assert cli.walk_forward_research(Path("unused"), store.path) == 0
    report = json.loads((config.backtest.report_directory / "walk-forward-EURUSD-fixture.json").read_text())
    assert report["experiment"]["analysis"]["rsi_period"] == config.analysis.rsi_period
    assert report["validation"]["final_holdout_evaluated"] is False
    assert report["strategy_validated"] is False
    assert report["costs_complete"] is False
