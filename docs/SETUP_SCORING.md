# Setup scoring implementation

The setup score estimates expected **net R**, then expresses it as the percentile of the
calibrated prediction in the fitting distribution. It is separate from the existing technical
conviction. A constant prediction produces score 50 rather than giving every trade 100.

`config.yaml` defaults to `scoring.enabled: false` and `scoring.shadow: true`. With no model,
candidates record `setup_score.status: unavailable`; the existing risk policy continues.
A valid model adds its score, expected R, band, features and SHA-256 to every candidate,
including candidates subsequently blocked by portfolio or broker limits. Executed trades
retain that evidence; learning adds `score:Q1` through `score:Q5` buckets. The model hash
participates in the learning strategy version. Telegram trade alerts include score and actual risk.
Shadow score buckets are diagnostic and cannot affect sizing. Baseline learning history is
kept under a separate sizing version, so loading/replacing a shadow model does not reset the
existing learning reductions. Score buckets can affect learning sizing only after activation.

## Export opportunities

Install the optional offline training dependencies:

```powershell
python -m pip install -e ".[dev,score-training]"
```

Export each historical database using **the same configuration and paper exit rules**:

```powershell
python scripts/export_setup_dataset.py --research-database data/dukascopy-2012-2018.sqlite3 --start 2012-01-01 --end 2019-01-01 --cost-pips EURUSD=0.9 GBPUSD=1.2 USDJPY=1.0 --cost-provenance "Assumed round-trip costs from causal replay, not observed costs" --out data/setups-2012-2018.csv
python scripts/export_setup_dataset.py --research-database data/dukascopy-research.sqlite3 --start 2019-01-01 --end 2026-09-29 --cost-pips EURUSD=0.9 GBPUSD=1.2 USDJPY=1.0 --cost-provenance "Assumed round-trip costs from causal replay, not observed costs" --out data/setups-2019-2026.csv
```

These costs reproduce the existing replay assumptions, not genuine historical transaction costs.
Supply measured costs when available. Every exported symbol requires an explicit cost; the
exporter never guesses a cost for a new pair. The exporter calls `causal_replay.analyse_pair`
with feature retention enabled. It records every primary-rule candidate, including overlapping
opportunities and candidates below the old conviction threshold. The current rule is whatever
`analysis.allowed_setups` permits; this does not deploy the experimental swing-structure rule.

Each CSV has decision/exit timestamps, pair, setup, net R, cost R, net R at twice costs,
hourly equity paths in R (outcome data, never features), and normalized features.
Its adjacent `.metadata.json` records the dataset SHA-256, analysis
settings, exit rules, costs, censored counts, and research limitations. Prices, raw ATR, broker
spread points, volume and account balances are excluded from model features. Unknown or
nonfinite features are rejected during training. Hashes are checked before training.

Outcomes use the configured paper target, breakeven at 1R, and configured ATR trailing after
breakeven, adverse intrabar ordering and gap-at-open stop fills. Entries use the decision close,
as in causal replay. Trades unresolved at the export boundary are excluded and counted.
Bid-only research cannot recreate actual bid/ask fills, review delays, swaps or broker H4
alignment; the artifact records those limits. Export sufficiently long continuous windows
to avoid discarding long-lived trades at short export boundaries.

For final confirmation, export AUDUSD, USDCAD, USDCHF, NZDUSD, EURJPY and GBPJPY using
`--symbols`, with explicit costs for each, in both periods. Those six pairs are excluded from
all fitting and calibration. The absence of their data prevents acceptance.

## Train and inspect the scorecard

```powershell
python scripts/train_setup_score.py --dataset data/setups-2012-2018.csv data/setups-2019-2026.csv data/setups-confirmation.csv --as-of 2026-10-03 --out data/models/setup-score-v1.json
```

The fixed model order is a four-feature tercile bucket table with shrinkage, standardized L2
ridge regression, 50-neighbor analogues, then depth-two monotone boosted trees. Hyperparameters
are fixed before evaluation. The tree hypothesis constrains stronger H4 persistence to a
nondecreasing prediction; it is a hypothesis for validation, not an established market fact.
All models are serialized to portable JSON; runtime scoring needs no numerical/ML dependency.
Isotonic calibration uses a separate earlier validation year.

Yearly walk-forward folds fit on earlier data, calibrate on the preceding year, and test on the
next year. Training and calibration labels must have completed before their boundary minus
the embargo. The embargo is at least the longest completed trade in the supplied history;
`--embargo-hours` can increase it. Insufficient folds are explicitly reported. With unlimited
live holding time, the observed maximum is an empirical bound, not a guaranteed future maximum.
No label after `--as-of` is available to training or evaluation.

The trainer evaluates T1–T7 separately in 2012–2018 and 2019–2026. T1 and T6 use pair/month
block bootstrap intervals to retain dependence between overlapping hourly candidates. T5
uses 1,000 random permutations. T4 compares the same executable opportunities at the same
maximum risk, with one position per pair and at most four positions; expected R <= 0 receives
zero allocation. Its log growth and drawdown use the combined hourly mark-to-market equity
and net exit fills. Missing equity paths fail T4. Hourly sampling cannot capture every
intrabar tick; the artifact records that resolution limit.

The first model passing development tests receives one unseen-pair confirmation. Confirmation
does not select or tune another model. All six pairs must appear in each confirmation period;
at least four of them must pass the stability test. If development fails, the bucket model is
saved for shadow use, and confirmation remains untouched. Missing samples, collapsed score
quintiles/deciles or failed tests never count as passing evidence.

The output prints `score-model v1: N/7 passed`. The JSON includes per-period tests,
confirmation tests, fold windows, scaler, model, calibration table, percentile distribution,
dataset provenance, sizing settings and SHA-256. The adjacent `.candidates.json` records
development results for attempted models. The scripts do not modify the running configuration.
Research data and model artifacts stay in the Git-ignored `data/` directory.

## Shadow and activation

Set `model_path` to the exported JSON and restart paper operation to load it. Leave
`shadow: true`: scores are recorded while the existing policy determines size. Invalid/missing
shadow artifacts are reported as unavailable. A model load verifies its content hash and
feature schema; a model with different analysis/exit rules is unavailable.

Activation requires deliberately setting `enabled: true` and `shadow: false`. Startup refuses
activation unless all seven tests pass in both periods and unseen-pair confirmation, sizing
settings and analysis/exits match the artifact, and the paper journal contains successful
shadow candidate scores spanning at least 28 days for **that same model hash and strategy**.
Retraining creates a new hash and requires new shadow evidence.

Dynamic risk is `kelly_fraction * expected_r / variance_r`, clamped to the configured minimum
and maximum (defaults 0.25% and 5%). Nonpositive expected R is skipped before applying the
minimum. The function returns a balance fraction: 0.01 means 1%. For expected R 0.03, variance
1.1 and quarter Kelly, this is about 0.68%. Risk blocks, leverage, position limits, daily circuit
breakers, per-pair limits and context ceilings remain enforced outside the model. Existing
learning/context size reductions can still lower the permitted size.

This checkout has no historical research databases or trained model. Implementation tests
use explicitly synthetic unit fixtures; they do not establish an accepted trading model or
complete the elapsed shadow period.
