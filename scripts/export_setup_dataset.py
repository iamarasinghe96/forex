"""Export every primary-rule opportunity, including rejected/overlapping candidates.

Uses causal replay with the configured paper exits (the live protective_stop rule), decision-close
entries and explicitly supplied round-trip costs. Bid-only fills/cost assumptions are recorded as
research limitations. Unresolved trades, including any spanning a data hole of --max-gap-hours,
are counted and excluded, never labelled as completed outcomes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import timedelta
from pathlib import Path

from causal_replay import analyse_pair, outcomes, pip
from research_db import require_data

from forex.config import load_config
from forex.scoring import FEATURE_SCHEMA, strategy_signature


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research-database", required=True)
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--symbols", nargs="+", help="Include the six unseen confirmation pairs")
    parser.add_argument("--start", required=True, help="ISO date; warmup data is loaded before this date")
    parser.add_argument("--end", required=True, help="Exclusive ISO date; unresolved outcomes are excluded")
    parser.add_argument("--cost-pips", nargs="+", required=True, help="Explicit round-trip costs: EURUSD=0.9 ...")
    parser.add_argument("--cost-provenance", required=True, help="Observed source or clearly labelled assumption")
    parser.add_argument("--out", required=True, type=Path, help="CSV output with adjacent .metadata.json")
    parser.add_argument("--max-gap-hours", type=int, default=48, help="Data holes that split the history")
    args = parser.parse_args()
    config = load_config(Path(args.config))
    symbols = [s.upper() for s in (args.symbols or config.broker.symbols)]
    costs = {pair.upper(): float(value) for pair, value in (item.split("=", 1) for item in args.cost_pips)}
    if any(s not in costs for s in symbols) or any(not math.isfinite(c) or c < 0 for c in costs.values()):
        parser.error("Supply a nonnegative finite cost for every pair; no guessed cross-pair defaults")
    if args.out.suffix.lower() != ".csv":
        parser.error("--out must be a CSV file")
    require_data(args.research_database, symbols)
    target = config.paper.target_reward_risk or config.risk.minimum_reward_risk
    metadata = {"schema": FEATURE_SCHEMA, "strategy_signature": strategy_signature(config),
                "analysis": config.analysis.model_dump(mode="json"),
                "exits": {"target_r": target, "breakeven_r": 1.0,
                          "trail_atr": config.paper.atr_trailing_multiple, "horizon_bars": 0},
                "cost_pips": costs, "cost_provenance": args.cost_provenance,
                "entry_rule": "decision-close", "start": args.start, "end_exclusive": args.end,
                "limitations": ["Bid-only research fills; live spread/review delay can change exits",
                                ("H4 bars must use the same fixed UTC alignment as the paper bot "
                                 "(market_data.h4_alignment_hour_utc); check with scripts/data_coverage.py")],
                "censored": 0, "invalid_stop": 0, "rows": 0}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as output:
        writer = None
        for symbol in symbols:
            print(f"Analysing {symbol} opportunities...", flush=True)
            _, hours, _ = analyse_pair((symbol, args.research_database, config.analysis.model_dump_json(),
                                        args.start, args.end, 0.0, args.max_gap_hours), include_features=True)
            labels = outcomes(symbol, hours, target, 1.0, config.paper.atr_trailing_multiple,
                              0, round_trip_cost_pips=costs[symbol], opportunities_only=True)
            for index, hour in enumerate(hours):
                if not hour.opportunity:
                    continue
                label = labels[index]
                if label is None:
                    metadata["invalid_stop"] += 1
                    continue
                exit_index, gross_r, label_cost_r, censored = label
                net_r = gross_r - label_cost_r
                if censored:
                    metadata["censored"] += 1
                    continue
                risk = abs(hour.close - hour.stop)
                cost_r = costs[symbol] * pip(symbol) / risk
                path = [[(hour.time + timedelta(hours=1)).isoformat(), -cost_r]]
                path.extend([[(hours[j].time + timedelta(hours=1)).isoformat(),
                              (hours[j].close - hour.close) * hour.direction / risk - cost_r]
                             for j in range(index + 1, exit_index)])
                path.append([(hours[exit_index].time + timedelta(hours=1)).isoformat(), net_r])
                row = {"decision_time": (hour.time + timedelta(hours=1)).isoformat(),
                       "exit_time": (hours[exit_index].time + timedelta(hours=1)).isoformat(),
                       "pair": symbol, "setup": hour.setup, "net_r": net_r,
                       "cost_r": cost_r, "net_r_2x_cost": net_r - cost_r,
                       "r_path_json": json.dumps(path, separators=(",", ":")), **hour.features}
                if writer is None:
                    writer = csv.DictWriter(output, fieldnames=list(row))
                    writer.writeheader()
                writer.writerow(row)
                metadata["rows"] += 1
    if not metadata["rows"]:
        raise SystemExit("No completed opportunities in this window; no training dataset was produced")
    metadata["dataset_sha256"] = hashlib.sha256(args.out.read_bytes()).hexdigest()
    args.out.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Exported {metadata['rows']} opportunities; excluded {metadata['censored']} unresolved trades")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
