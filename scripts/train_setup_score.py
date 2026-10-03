"""Train setup score models in fixed order, with purged yearly folds and unseen-pair confirmation."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from setup_score_training import (
    MODEL_ORDER,
    aggregate_card,
    audit_invariance,
    fit_model,
    purged_split,
    read_datasets,
    scorecard_period,
    transfer_predictions,
    walk_forward,
)

from forex.config import load_config
from forex.scoring import PERIODS, TRANSFER_PAIRS, model_hash, strategy_signature


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, nargs="+", required=True)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--training-pairs", nargs=3, default=["EURUSD", "GBPUSD", "USDJPY"])
    parser.add_argument("--embargo-hours", type=float, default=0, help="Raised to maximum observed completed trade length")
    parser.add_argument("--as-of", help="UTC ISO date/time; labels after this instant are unavailable")
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--out", type=Path, default=Path("data/models/setup-score-v1.json"))
    args = parser.parse_args()
    config = load_config(args.config)
    rows, provenance = read_datasets(args.dataset)
    if provenance["strategy_signature"] != strategy_signature(config):
        parser.error("Dataset analysis and exits do not match config; re-export the opportunities")
    as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    as_of = as_of.astimezone(UTC)
    rows = [row for row in rows if row.exit < as_of]
    if not rows:
        parser.error("No completed labels before --as-of")
    train_pairs = {p.upper() for p in args.training_pairs}
    transfer_pairs = set(TRANSFER_PAIRS)
    if train_pairs & transfer_pairs:
        parser.error("Confirmation pairs must never be used for fitting or calibration")
    embargo = max(timedelta(hours=args.embargo_hours), max(row.exit - row.decision for row in rows))
    signature, sizing = provenance["strategy_signature"], config.scoring
    candidates = []
    selected = None
    for kind in MODEL_ORDER:
        print(f"Fitting {kind} with embargo {embargo}...", flush=True)
        predictions, models, folds = walk_forward(rows, kind, train_pairs, signature, sizing, embargo)
        t7 = bool(models) and all(audit_invariance(m, config.analysis) for m in models.values())
        periods = {period: scorecard_period([p for p in predictions if (2012 <= p.opportunity.decision.year <= 2018
                                                                      if period == PERIODS[0] else 2019 <= p.opportunity.decision.year <= 2026)],
                                            sizing, train_pairs, t7, args.seed + index)
                   for index, period in enumerate(PERIODS)}
        dev_pass = all(periods[p][f"T{i}"]["passed"] for p in PERIODS for i in range(1, 8))
        candidates.append({"kind": kind, "periods": periods, "folds": folds, "development_passed": dev_pass})
        if selected is None:
            selected = (kind, models, periods, folds, t7)
        if dev_pass:
            selected = (kind, models, periods, folds, t7)
            break  # Confirmation data never selects a different model or tunes parameters.
    kind, models, periods, folds, t7 = selected
    development_passed = all(periods[p][f"T{i}"]["passed"] for p in PERIODS for i in range(1, 8))
    transfer = {}
    if development_passed:
        predictions = transfer_predictions(rows, models, transfer_pairs)
        transfer = {period: scorecard_period([p for p in predictions if (2012 <= p.opportunity.decision.year <= 2018
                                                                      if period == PERIODS[0] else 2019 <= p.opportunity.decision.year <= 2026)],
                                            sizing, transfer_pairs, t7, args.seed + 100 + index)
                    for index, period in enumerate(PERIODS)}
        # All six confirmation pairs must actually have OOS examples in each period.
        for period in PERIODS:
            if set(transfer[period]["observed_pairs"]) != transfer_pairs:
                transfer[period]["T3"]["passed"] = False
                transfer[period]["T3"]["reason"] = "Missing unseen-pair coverage"
    card = aggregate_card(periods, transfer, transfer_pairs)
    train, calibration = purged_split(rows, as_of, embargo, train_pairs)
    model = fit_model(kind, train, calibration, signature, sizing)
    if not audit_invariance(model, config.analysis):
        for scope in (periods, transfer):
            for period in scope:
                scope[period]["T7"]["passed"] = False
        card = aggregate_card(periods, transfer, transfer_pairs)
    document = dict(model.document)
    document.update(scorecard=card, folds=folds, dataset_provenance=provenance,
                    embargo_seconds=embargo.total_seconds(), training_pairs=sorted(train_pairs),
                    as_of=as_of.isoformat(), status="accepted_pending_shadow" if card["passed"] else "shadow_only",
                    research_limitations=["Assumed costs are not observed execution costs",
                                          "Sizing drawdown sampled at hourly closes and exit fills, not tick-by-tick",
                                          "Unlimited live holding time: embargo bounds observed completed trades"])
    document["sha256"] = model_hash(document)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2, allow_nan=False), encoding="utf-8")
    args.out.with_suffix(".candidates.json").write_text(json.dumps(candidates, indent=2, allow_nan=False), encoding="utf-8")
    print(card["line"])
    print(f"Wrote {args.out}; {document['status']}. Four weeks of shadow evidence are required before activation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
