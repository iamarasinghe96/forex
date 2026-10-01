"""Scan which protective layers cost trades, over stored candles (read-only, exploratory).

Usage: python scripts/scan_protections.py --since 2025-11-01 [--until 2026-10-01]
       [--db <paper database>] [--config config.yaml] [--balance 100] [--audusd 0.66]

Replays the bot's hourly analysis with one protective layer removed at a time, then simulates
one position per pair with the live exit rules. Compares each variant with the current rules:
a layer that "costs money" shows a better net result when removed. Analysis variants are
replayed in parallel processes; allow several minutes for a year. Results on data the bot was
tuned or checked on are exploration only - anything promising must pass the pre-registered
2012-2018 and 2021-2025 tests before it is switched on.
"""
from __future__ import annotations

import argparse
import math
import os
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from forex.analysis import InsufficientDataError, analyse_market, prepare_candles
from forex.config import AnalysisConfig, load_config
from forex.domain import Candle, Timeframe

COST_PIPS = {"EURUSD": 0.9, "GBPUSD": 1.2, "USDJPY": 1.0}  # Same assumptions as the research scripts.
ANALYSIS_VARIANTS: dict[str, dict[str, object]] = {
    "current rules": {},
    "J6-a volatility block off": {"high_volatility_blocks_trend": False},
    "J6-b faster trend (10 bars)": {"trend_efficiency_window": 10},
    "J6-a + J6-b": {"high_volatility_blocks_trend": False, "trend_efficiency_window": 10},
    "setup-strength threshold off": {"setup_score_threshold": 0.0},
    "range setups on": {"allowed_setups": ["TREND_CONTINUATION_BREAKOUT_PULLBACK", "RANGE_MEAN_REVERSION"]},
}
# (label, target R, ATR trail multiple, break-even on, conviction minimum on, account-size minimum on)
SIM_VARIANTS = [
    ("current rules", 1.5, None, True, True, True),
    ("target 3R", 3.0, None, True, True, True),
    ("trail 3x ATR, no target", 1000.0, 3.0, True, True, True),
    ("break-even at +1R off", 1.5, None, False, True, True),
    ("conviction minimum off", 1.5, None, True, False, True),
    ("minimum-lot limit off", 1.5, None, True, True, False),
]
RISK_LIMITS_OFF = ("  + conviction & min-lot limits off", 1.5, None, True, False, False)

# One hour: (time, open, high, low, close, candidate) with candidate = (side, stop, conviction, h1_atr).
Hour = tuple[datetime, float, float, float, float, tuple[int, float, float, float] | None]


def pip(symbol: str) -> float:
    return 0.01 if symbol.endswith("JPY") else 0.0001


def load(db_path: Path, stored: str, symbol: str, timeframe: Timeframe) -> list[Candle]:
    db = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    rows = db.execute(
        "SELECT timestamp_utc, open, high, low, close, tick_volume, spread, real_volume FROM candles "
        "WHERE symbol=? AND timeframe=? ORDER BY timestamp_utc", (stored, timeframe.value)).fetchall()
    db.close()
    return [Candle.from_values(symbol, timeframe, datetime.fromisoformat(r[0]).astimezone(UTC), *r[1:])
            for r in rows]


def replay(job: tuple[str, str, str, Path, str, datetime, datetime]) -> tuple[str, str, list[Hour]]:
    variant, symbol, stored, db_path, config_json, since, until = job
    config = AnalysisConfig.model_validate_json(config_json)
    h1 = load(db_path, stored, symbol, Timeframe.H1)
    p1 = prepare_candles(h1, config)
    p4 = prepare_candles(load(db_path, stored, symbol, Timeframe.H4), config)
    hours: list[Hour] = []
    for candle in h1:
        if not since <= candle.timestamp_utc < until:
            continue
        now = candle.timestamp_utc + timedelta(hours=1)
        try:
            candidate = analyse_market(symbol, p1.closed(now), p4.closed(now), now, config).candidate
        except InsufficientDataError:
            continue
        info = None
        if candidate is not None:
            long = candidate.side.value == "LONG"
            stop = float(candidate.structural_reference_levels["rolling_low" if long else "rolling_high"])
            info = (1 if long else -1, stop, (1 - candidate.uncertainty) * 100,
                    float(candidate.feature_snapshot["h1_atr"]))
        hours.append((now, float(candle.open), float(candle.high), float(candle.low),
                      float(candle.close), info))
    return variant, symbol, hours


@dataclass
class Result:
    trades: int = 0
    wins: int = 0
    net_r: float = 0.0
    aud: float = 0.0
    skipped_conviction: int = 0
    skipped_min_lot: int = 0
    still_open: int = 0
    max_risk_percent: float = 0.0

    def add(self, r: float, aud: float) -> None:
        self.trades += 1
        self.wins += r > 0
        self.net_r += r
        self.aud += aud


def simulate(symbol: str, hours: list[Hour], variant: tuple, thresholds: dict[str, float],
             risks: dict[str, float], balance: float, audusd: float, result: Result) -> None:
    _, target_rr, trail, breakeven_on, conviction_on, min_lot_on = variant
    cost = COST_PIPS.get(symbol, 1.0) * pip(symbol)
    position: dict[str, float] | None = None

    def close(price: float) -> None:
        assert position is not None
        move = (price - position["entry"]) * position["sign"] - cost
        aud_per_unit = 100_000 / audusd / (position["entry"] if symbol.startswith("USD") else 1.0)
        result.add(move / position["risk"], move * position["lots"] * aud_per_unit)

    for now, _, high, low, close_price, info in hours:
        if position is not None:
            sign = position["sign"]
            adverse, favourable = (low, high) if sign > 0 else (high, low)
            if (adverse - position["stop"]) * sign <= 0:
                close(position["stop"])
                position = None
            elif (favourable - position["target"]) * sign >= 0:
                close(position["target"])
                position = None
            else:
                if breakeven_on and (favourable - position["entry"]) * sign >= position["risk"]:
                    position["stop"] = position["entry"] if (position["entry"] - position["stop"]) * sign > 0 \
                        else position["stop"]
                    position["trailing"] = 1.0
                if trail is not None and position.get("trailing"):
                    proposed = close_price - sign * trail * position["atr"]
                    if (proposed - position["stop"]) * sign > 0:
                        position["stop"] = proposed
        if position is None and info is not None:
            sign, stop, conviction, atr = info
            risk = (close_price - stop) * sign
            if risk <= 0:
                continue
            if conviction < thresholds["minimum"]:
                if conviction_on:
                    result.skipped_conviction += 1
                    continue
                percent = risks["low"]
            else:
                percent = (risks["high"] if conviction >= thresholds["high"] else
                           risks["medium"] if conviction >= thresholds["medium"] else risks["low"])
            aud_per_unit = 100_000 / audusd / (close_price if symbol.startswith("USD") else 1.0)
            loss_per_lot = risk * aud_per_unit
            lots = math.floor(balance * percent / 100 / loss_per_lot / 0.01) * 0.01
            if lots < 0.01:
                if min_lot_on:
                    result.skipped_min_lot += 1
                    continue
                lots = 0.01
            result.max_risk_percent = max(result.max_risk_percent, 100 * lots * loss_per_lot / balance)
            position = {"sign": sign, "entry": close_price, "stop": stop, "risk": risk, "atr": atr,
                        "target": close_price + sign * target_rr * risk, "lots": lots}
    if position is not None:
        result.still_open += 1
        close(hours[-1][4])  # Marked to the last close so long-holding variants are comparable.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=None, help="Default: paper.database in the config")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--since", required=True, help="UTC date; the first ~40 days of stored history are warm-up")
    parser.add_argument("--until", default=None, help="UTC date (exclusive); default now")
    parser.add_argument("--balance", type=float, default=None, help="Account size in AUD (default: paper balance)")
    parser.add_argument("--audusd", type=float, default=0.66, help="AUD/USD rate for sizing (approximate)")
    args = parser.parse_args()
    missing = {"high_volatility_blocks_trend", "trend_efficiency_window"} - set(AnalysisConfig.model_fields)
    if missing:
        raise SystemExit("This scan needs the J6 strategy code (commit 2ded460 or later) on PYTHONPATH.")
    config = load_config(args.config)
    args.db = args.db or config.paper.database
    balance = args.balance or config.paper.starting_balance_aud or 100.0
    since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
    until = datetime.fromisoformat(args.until).replace(tzinfo=UTC) if args.until else datetime.now(UTC)
    db = sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True)
    stored = [row[0] for row in db.execute("SELECT DISTINCT symbol FROM candles")]
    db.close()
    symbols = {}
    for symbol in config.broker.symbols:
        match = next((s for s in stored if s.upper().split(".")[0] == symbol.upper()), None)
        if match:
            symbols[symbol.upper()] = match
    jobs = [(name, symbol, stored_name, args.db,
             config.analysis.model_copy(update=changes).model_dump_json(), since, until)
            for name, changes in ANALYSIS_VARIANTS.items() for symbol, stored_name in symbols.items()]
    print(f"Replaying {len(jobs)} variant/pair combinations from {since:%Y-%m-%d} "
          f"(balance A${balance:.0f}); this can take several minutes...", flush=True)
    streams: dict[tuple[str, str], list[Hour]] = {}
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as pool:
        for variant, symbol, hours in pool.map(replay, jobs):
            streams[(variant, symbol)] = hours
            print(f"  done: {variant} / {symbol}", flush=True)
    thresholds = {k: float(v) for k, v in config.risk.conviction_thresholds.items()}
    risks = {k: float(v) for k, v in config.risk.conviction_risk_percent.items()}
    rows = []
    for analysis_name in ANALYSIS_VARIANTS:
        sims = [*SIM_VARIANTS] if analysis_name == "current rules" else [SIM_VARIANTS[0]]
        sims.append(RISK_LIMITS_OFF)
        for sim in sims:
            label = analysis_name if sim is SIM_VARIANTS[0] else sim[0]
            result = Result()
            for symbol in symbols:
                simulate(symbol, streams[(analysis_name, symbol)], sim, thresholds, risks,
                         balance, args.audusd, result)
            rows.append((label, result))
    base = rows[0][1]
    print("\nLayer removed                         trades  win%   net R   A$ P&L   vs now"
          "  skipped conv/min-lot  open  max risk%")
    for label, r in rows:
        win = 100 * r.wins / r.trades if r.trades else 0.0
        print(f"{label:37s} {r.trades:6d} {win:5.0f} {r.net_r:+7.2f} {r.aud:+8.2f} {r.aud - base.aud:+8.2f}"
              f"  {r.skipped_conviction:8d}/{r.skipped_min_lot:<8d} {r.still_open:5d} {r.max_risk_percent:8.1f}")
    print("\nNet R is the sum of per-trade results after costs; A$ P&L uses the bot's 2-5% conviction"
          "\nsizing on a fixed balance with 0.01-lot minimum; with the min-lot limit off a wide stop"
          "\nforces 0.01 lot, so a trade can risk more than 5% (see max risk%)."
          "\nIndented rows remove the conviction and min-lot limits on top of the row above."
          "\nOpen trades are marked to the last close."
          "\nNot modelled: AI news review, daily loss limit, spread changes, slippage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
