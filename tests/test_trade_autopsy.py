from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_learning import runtime_fixture
from test_risk import NOW

from forex.domain import Tick


def autopsy():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("trade_autopsy", Path("scripts/trade_autopsy.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_explains_a_stopped_trade_without_changing_the_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                               capsys: pytest.CaptureFixture[str]) -> None:
    runtime, paper, feed = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()
    stop = paper.positions()[0].stop
    feed.tick.return_value = Tick("EURUSD", stop - Decimal("0.0002"), stop - Decimal("0.0001"),
                                  NOW + timedelta(hours=2))
    paper.manage(NOW + timedelta(hours=2))
    assert not paper.positions()
    before = paper.path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["trade_autopsy.py", "--db", str(paper.path), "--symbol", "EURUSD"])
    assert autopsy().main() == 0
    out = capsys.readouterr().out
    assert "EURUSD BUY" in out and "by STOP" in out
    assert "pips past the stop" in out and "WHY IT ENTERED" in out and "<- this trade" in out
    assert paper.path.read_bytes() == before


def test_reports_when_nothing_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    runtime, paper, _ = runtime_fixture(tmp_path, monkeypatch)
    runtime.cycle()
    monkeypatch.setattr(sys, "argv", ["trade_autopsy.py", "--db", str(paper.path)])
    assert autopsy().main() == 1
    assert "No closed trade" in capsys.readouterr().out
