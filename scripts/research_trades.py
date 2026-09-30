"""Research only: export every out-of-sample simulated candidate trade with its attributes.

Replays the same walk-forward test windows as `forex walk-forward-research` (baseline parameters,
no optimisation, final holdout excluded) and writes one CSV row per simulated trade, including
the Layer 5 conviction score the live bot would have used. It never places orders or changes
configuration. Usage (from the repository root):
    .venv\\Scripts\\python.exe scripts\\research_trades.py --research-database data\\dukascopy-research.sqlite3
"""
from __future__ import annotations

import argparse
import csv
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from forex.backtest import build_walk_forward_folds, parameter_experiment, run_backtest
from forex.config import AppConfig, load_config
from forex.domain import Candle, Timeframe
from forex.risk import derive_conviction
from forex.risk_policy import policy_from_config

FIELDS = ["symbol", "fold", "signal_time_utc", "entry_time_utc", "exit_time_utc", "side",
          "setup_family", "trade_style", "regime", "volatility_bucket", "sessions",
          "conviction", "conviction_band", "entry_price", "stop_price", "initial_risk",
          "stop_pips", "exit_reason", "ambiguous", "gross_r", "mfe_r", "mae_r", "holding_bars"]


def pip_size(symbol: str) -> float:
    return 0.01 if symbol.upper().endswith("JPY") else 0.0001


ALL_SETUPS = ["TREND_CONTINUATION_BREAKOUT_PULLBACK", "RANGE_MEAN_REVERSION"]


def export_symbol(symbol: str, h1: Sequence[Candle], h4: Sequence[Candle], config: AppConfig,
                  writer: Any, progress: TextIO | None = None,
                  window_start: datetime | None = None) -> tuple[int, datetime | None]:
    """Walk-forward test windows by default; with window_start, one window to the end of the data
    (for a separate, never-used dataset where no training split or holdout applies)."""
    policy = policy_from_config(config.risk)
    # Export every setup family so results stay comparable; the analysis scripts filter.
    analysis = parameter_experiment(config.analysis, {"allowed_setups": ALL_SETUPS}).analysis
    start = max(min(c.timestamp_utc for c in h1), min(c.timestamp_utc for c in h4))
    end = min(max(c.timestamp_utc + c.timeframe.duration for c in h1),
              max(c.timestamp_utc + c.timeframe.duration for c in h4))
    protocol = build_walk_forward_folds(start, end, config.backtest)
    windows = ([(0, window_start, end)] if window_start is not None else
               [(f.fold_number, f.test_start_utc, f.test_end_utc) for f in protocol.folds])
    count = 0
    for number, test_start, test_end in windows:
        result = run_backtest(symbol, h1, h4, analysis, config.backtest, policy, None,
                              test_start, test_end, test_end)
        conviction = {e.candidate.candidate_id: derive_conviction(e.candidate, policy)
                      for e in result.evaluations if e.candidate is not None}
        for t in result.trades:
            c = conviction.get(t.candidate_id)
            writer.writerow({
                "symbol": t.symbol, "fold": number, "signal_time_utc": t.signal_time_utc.isoformat(),
                "entry_time_utc": t.entry_time_utc.isoformat(), "exit_time_utc": t.exit_time_utc.isoformat(),
                "side": t.side.value, "setup_family": t.setup_family, "trade_style": t.trade_style,
                "regime": t.regime, "volatility_bucket": t.volatility_bucket, "sessions": "|".join(t.sessions),
                "conviction": "" if c is None else str(c.final_conviction),
                "conviction_band": "" if c is None else c.band.value,
                "entry_price": t.entry_price, "stop_price": t.stop_price, "initial_risk": t.initial_risk,
                "stop_pips": round(t.initial_risk / pip_size(symbol), 2), "exit_reason": t.exit_reason,
                "ambiguous": t.ambiguous, "gross_r": t.gross_r, "mfe_r": t.mfe_r, "mae_r": t.mae_r,
                "holding_bars": t.holding_bars,
            })
            count += 1
        if progress is not None:
            print(f"  {symbol} window {number}/{len(windows)}: {len(result.trades)} trades", file=progress, flush=True)
    return count, None if window_start is not None else protocol.final_holdout_start_utc


def main() -> None:
    import sys

    from forex.history import validate_research_database
    from forex.persistence import CandleStore

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--research-database", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--out", type=Path, default=Path("reports/backtest/oos-trades.csv"))
    parser.add_argument("--start-utc", type=datetime.fromisoformat,
                        help="Evaluate one window from this UTC time to the end of the data (separate dataset only)")
    parser.add_argument("--reward-risk", type=float, help="Fixed target in R (e.g. 1000 = effectively no target)")
    parser.add_argument("--atr-trailing", type=float, help="ATR trailing-stop multiple after break-even")
    parser.add_argument("--horizon-bars", type=int, help="Maximum holding time in H1 bars")
    args = parser.parse_args()
    config = load_config(args.config)
    for name, value in (("reward_risk", args.reward_risk), ("atr_trailing_multiple", args.atr_trailing),
                        ("simulation_horizon_bars", args.horizon_bars)):
        if value is not None:
            setattr(config.backtest, name, value)
    print(f"Exit model: target {config.backtest.reward_risk} R | break-even at {config.backtest.breakeven_at_r} R | "
          f"ATR trailing {config.backtest.atr_trailing_multiple} | max hold {config.backtest.simulation_horizon_bars} bars",
          flush=True)
    dataset, _ = validate_research_database(args.research_database, config.broker.symbols, config.market_data)
    store = CandleStore(args.research_database)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"Dataset {dataset.fingerprint[:12]}; writing {args.out}", flush=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for symbol in config.broker.symbols:
            count, holdout = export_symbol(symbol, store.load(symbol, Timeframe.H1),
                                           store.load(symbol, Timeframe.H4), config, writer, sys.stdout,
                                           args.start_utc)
            scope = (f"final holdout from {holdout} excluded" if holdout is not None
                     else f"single window from {args.start_utc}")
            print(f"{symbol}: {count} out-of-sample trades exported ({scope})", flush=True)


if __name__ == "__main__":
    main()
