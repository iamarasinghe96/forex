# Forex Operator — Layer 4 Historical Research

Layers 1–2 provide the verified read-only broker and market-data foundation. Layer 3 adds pure,
deterministic analysis and candidate generation; it still contains no risk sizing or order execution
and makes no claim of a validated trading edge.

Layer 4 adds broker-neutral historical replay, research-only next-bar trade simulation, normalized
performance measurement, bounded parameter experiments, chronological walk-forward folds, an
untouched final-holdout boundary, deterministic Monte Carlo outcome resampling, and a structured
historical baseline. It calls the **same** pure `analyse_market` Layer 3 entry point used by current
analysis and future runtime callers. It neither implements production risk/execution nor sends orders.

## Windows demo setup and verification

From PowerShell, with 64-bit Python 3.12 or 3.13 and MetaTrader 5 logged into the configured demo:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mt5,dev]"
.\.venv\Scripts\forex.exe verify-foundation
.\.venv\Scripts\forex.exe verify-market-data
```

Put the demo trading password only in the ignored `.env` file. The market-data command verifies
fresh ticks and recent candles, then downloads every H1/H4 chunk currently exposed by MT5 into the
configured SQLite database. Success ends with:

```text
Layer 2 verification passed. Historical candles were saved; no order was sent.
```

Each series reports its actual earliest/latest UTC times, candle count, depth in days/years, expected
weekend gaps, and unexplained gaps. A warning below five years means later backtesting lacks its
desired depth; it is not filled, purchased, or fabricated. MT5 availability depends on the broker,
terminal cache, loaded charts, and **Tools → Options → Charts → Max bars in chart**. Increase that
setting, restart/load each chart, and rerun safely; SQLite upserts are idempotent and can update the
forming candle.

## Layer 3 analysis / strategy

Layer 3 is a read-only, broker-neutral deterministic analysis pipeline shared by future live, paper,
replay, walk-forward, and attribution callers. It does not connect to MT5: `forex verify-analysis`
loads the existing SQLite H1/H4 history, uses only bars satisfying `timestamp_utc + duration <=
evaluation_time`, and prints one analysis snapshot per configured pair. Actual normalized timestamps are
used, so H4 is never assumed to start at UTC multiples of four hours. If data is missing or stale, run
`forex verify-market-data`; analysis never silently fetches data and never sends an order.

H4 supplies graded direction, persistence, range, momentum, volatility-rank and structural-breakout
context. H1 supplies tactical continuation/pullback or range-reversion evidence. EMA relationships and
slope, multi-horizon returns, directional efficiency, RSI, MACD, ATR/price, realised volatility,
volatility rank, rolling levels, breakout distances, range position, mean deviation, body/wicks,
range expansion, follow-through, broker tick volume and broker spread points form the feature snapshot.
Tick volume is broker activity, **not centralized global FX volume**.

Every call returns an `AnalysisSnapshot`, including no-trade calls, with a deterministic evaluation ID,
versioned features/regime/setup measurements, last closed bars, supporting and opposing evidence,
no-candidate reason, session, volatility and macro availability. A coherent setup can additionally
produce a `TradeCandidate`; it contains analytical evidence and structural references but no size,
risk percentage, SL/TP, or broker order fields. Trend continuation is automatically DAY or SWING from
H4 persistence; range reversion is initially DAY. These rules and all thresholds are UNVALIDATED.

Macro is a provider-neutral relative base/quote contract. With no genuine provider it is explicitly
`UNAVAILABLE`: it supplies neither bullish nor bearish evidence, does not reduce technical strength,
and does not veto a candidate. No news, sentiment, probabilities, scenarios, or LLM output is invented.

```powershell
.\.venv\Scripts\forex.exe verify-analysis
```

Expected output includes evaluation UTC, latest closed H1/H4 timestamps, regime, directional and
volatility measurements, setup/style, evidence, candidate/direction, macro availability, and strategy
and parameter versions, ending with `Layer 3 analysis verification passed... no order was sent.`

## Layer 4 backtest verification

```powershell
.\.venv\Scripts\forex.exe verify-backtest
.\.venv\Scripts\forex.exe validate-backtest
```

`verify-backtest` is an engine-verification command: it reads SQLite only, evaluates every H1 close
after warm-up, reports candidate and simulated-trade frequency, and writes deterministic research
content to `reports/backtest/strategy-baseline.json`. It requires neither MT5 nor `.env`, an LLM, a
news feed, or fabricated macro data. `validate-backtest` runs the same replay but exits with code 3
unless every pair has at least five years in both H1 and H4. The expected current VPS depth of about
0.74 years therefore produces **INSUFFICIENT HISTORY FOR FIVE-YEAR VALIDATION** while still allowing
engine checks and metrics. This is not a failed engine check and never becomes a validation claim.

Both commands reserve the configured final holdout before replay: decisions and forward outcomes
stop at its boundary. The baseline contains pre-holdout research metrics and planned walk-forward
windows only; these commands do not execute fold selection or measure aggregate OOS performance.
An exit code of zero from `validate-backtest` establishes the history-depth gate and successful
engine replay, not strategy approval. Generated research reports remain local and are ignored by Git.

Historical replay prepares immutable, ordered candle prefixes and recursive EMA/MACD histories once.
The same `analyse_market` entry point consumes only the prefix closed at each decision time. Recursive
indicators retain the original full-history seed and arithmetic; finite-window features retain their
original windows. The ordinary sequence path remains available as the reference implementation.

At each event, evaluation time is the actual H1 timestamp plus one hour. Layer 3 independently filters
H1 and H4 to candles whose actual timestamp plus duration is closed, so forming candles and future H4
states cannot leak in. No UTC modulo rule is used for H4. Forward paths are attached only after the
immutable decision snapshot and are clearly labelled outcomes; no-trade snapshots and their exact
rejection reason are retained rather than being discarded or called fabricated “missed trades.”

Research fills use the next available H1 open. Stops derive from the candidate's existing structural
reference; targets begin at the explicitly configured 1.5R. Breakeven and ATR-trailing changes become
active only after a complete bar, because OHLC cannot establish intrabar ordering. If stop and target
are both touched, primary reporting uses deterministic adverse/stop-first treatment. The alternative
`ambiguous` policy still records an unresolved ambiguity at the stop value; it never awards the target.
All horizons and exit settings are explicit, configurable, and **UNVALIDATED**.

The `CostModel` separates observed candle spread, commission, slippage, and other costs. Spread points
are convertible only with explicitly captured runtime instrument metadata and remain marked
UNVALIDATED because a bar field is not a tick-at-fill quote. Commission, slippage, swap, and fees are
never guessed. Reports separate gross and net-known-cost results and declare an incomplete model.

Metrics include counts/frequency, win/loss rates, average wins/losses, expectancy, profit factor,
payoff, cumulative R, drawdown, streaks, MAE/MFE, holding time, and direction/pair/setup/regime/session/
DAY-or-SWING breakdowns. The desired 3–8 weekly trades is calibration context, not a veto or proof.
Raw candidate evaluations are preserved. A setup episode is a contiguous run with the same symbol,
side, and setup family and ends on a no-candidate state, direction change, or family change. Episodes
are analytical persistence metadata only: neither candidate evaluations, episodes, nor overlapping
independent candidate simulations claim to be future live orders. Simulation drop-off is attributed as
`NO_NEXT_BAR`, `NON_POSITIVE_INITIAL_RISK`, or `WINDOW_BOUNDARY_CENSORED` rather than disappearing.
Stable `research-<hash>` experiment versions vary validated `AnalysisConfig` copies without editing
`config.yaml` or promoting `unvalidated-v1`. Walk-forward selection sees each training window only,
then measures the selected version on its subsequent test; folds stop before the reserved final
holdout. IID bootstrap Monte Carlo uses a recorded seed and measures outcome-distribution uncertainty,
not synthetic prices or account-specific ruin; serial/regime-dependence limitations are reported.

Walk-forward outcomes are calculated inside each fold boundary. A position or forward label that has
not resolved before that boundary is censored and excluded from expectancy; test or final-holdout bars
are never used to complete an earlier window's outcome.

The baseline is intended for a future learning layer to compare candidate *and rejection* behaviour,
not to implement “three losses means block trades,” mutate strategy parameters, or veto candidates.

## Layer 5: deterministic exposure ceiling

Layer 5 is calculation and policy only: it cannot place, modify, or close an order. Its
technical conviction is exactly `(1 - Layer 3 candidate uncertainty) * 100`; the obsolete
prototype 50/25/25 blend was not restored. Unavailable context is excluded and neutral, not
converted to zero, opposition, or a veto. The versioned, **UNVALIDATED operator calibration**
is below 55 ineligible, 55–<70 at 2%, 70–<85 at 3.5%, and 85–100 at 5% balance risk.
All operator values—including the 55/70/85 boundaries—come solely from the validated `risk`
section of `config.yaml`; the pure engine receives an immutable `RiskPolicy` and never reads YAML.

Sizing uses runtime broker metadata: `loss_per_lot = abs(entry-stop) / tick_size * tick_value`
and `raw_volume = balance * risk_percent / loss_per_lot`. Volume is floored to `volume_step`,
never raised to `volume_min`, and may be capped at `volume_max`; the result is rejected if the
minimum volume would exceed budget. Structural Layer 3 invalidation is retained, must be on
the correct side of entry, and must satisfy `stops_level_points * point`. The minimum objective
is exactly 1.5R (a policy reference, not a mandatory hard take-profit).

Portfolio policy permits at most four open positions and 20% of current balance in remaining
worst-case stop risk. Breakeven-or-better stops contribute zero, never negative credit. USD
currency-direction concentration is reported without a hidden correlation veto. A 12% loss
from explicit session-opening balance latches the daily circuit breaker; an independent kill
switch also blocks entries. Either emits `FLATTEN_REQUIRED` intent, but Layer 5 performs no
flattening. The latch has transactional SQLite persistence.

At +1R, the protective stop may move to entry. ATR trailing can begin only after that stage,
never loosens a stop, and has no guessed default: its multiple is currently
`UNVALIDATED_NOT_CONFIGURED`. Future Layer 6 may approve unchanged, reduce volume, or veto;
it cannot enlarge volume/risk, loosen the stop, lower 1.5R, or override portfolio/halt/leverage
limits. Recent losses do not modify conviction or disable a setup: learning remains a future,
versioned research/promotion process.
Only an `ELIGIBLE` decision exposes `permitted_position_plan`; blocked mathematical proposals
are retained, when available, solely as explicitly non-actionable diagnostics. The Layer 6 ceiling
also requires a reviewed objective to preserve the directional minimum 1.5R objective.

Layer 4 uses the same Layer 5 conviction function and reports raw-candidate and setup-episode
band counts separately, plus band-segmented normalized-R results. These are not live trades,
and unavailable historical account-currency metadata is not fabricated. Formal status remains
`INSUFFICIENT HISTORY FOR FIVE-YEAR VALIDATION` until five real years exist. Run
`forex verify-risk` for a read-only current calculation; its portfolio check deliberately uses a
zero-position verification fixture because Layer 7 reconciliation does not exist.

## External historical research data

No external vendor is selected by this repository: provider claims could not be verified in this
environment. Instead, `import-history` accepts deliberately obtained H1 CSV with
`timestamp,open,high,low,close` and optional `volume,spread`. Timestamps must be explicitly UTC and
rows strictly increasing. Invalid OHLC, duplicates, naive timestamps, and conflicting overlaps fail;
gaps are never filled.

Always use a dedicated `--research-database`, never the configured IC Markets database. Provenance
records provider/release, pair, granularity, UTC, price type, spread/volume availability, coverage,
row count, import time, transformations, input hash and H4 policy. H4 uses only four complete H1 bars
under an explicit fixed UTC alignment hour; it is not claimed equivalent to IC Markets broker-native
DST-dependent H4. Missing spread is provenance-marked unavailable, not a zero-cost assumption.
H1, H4, and provenance are committed in one SQLite transaction. Identical re-import returns the
original persisted import timestamp; changed metadata for the same identity, or any incompatible feed
semantics elsewhere in the database, is rejected. Claimed spread or volume requires a populated CSV
column on every row.

```powershell
.\.venv\Scripts\forex.exe import-history --research-database data\research.sqlite3 --file data\EURUSD.csv --dataset RELEASE_ID --provider PROVIDER --symbol EURUSD --price-type midpoint --volume-semantics unavailable --h4-alignment-hour-utc 0
.\.venv\Scripts\forex.exe verify-history --research-database data\research.sqlite3
.\.venv\Scripts\forex.exe validate-backtest --research-database data\research.sqlite3
```

Import all configured symbols only after independently verifying provider and licence. Five years only
makes formal validation eligible; it does not validate the strategy or relax any existing protocol.
Research replay first verifies provenance and writes `research-baseline-<fingerprint>.json`, leaving
the broker-native baseline untouched. The report binds results to the release/provider, symbols,
source hashes, semantics, alignment, coverage, and deterministic dataset fingerprint.

## Layer 6 constrained context review

`forex verify-context` validates the local prompt/configuration/JSON contract without a paid
provider call or MT5 connection. Context is disabled by default; set actual provider model IDs
and local .env keys before enabling it. No provider/free-tier/cost assumptions are fabricated.

The review accepts only approve/reject/reduce_size, a volume fraction, rationale and references
to supplied evidence. It cannot modify prices, stops, objectives, policy or strategy parameters.
Risk blocks bypass providers entirely. Reductions floor to the broker step and below-minimum
size is non-actionable. Missing context preserves the original eligible Layer 5 allowance.

Provider timeout/rate/error/malformed/schema failures retry with bounded backoff then fail over
in configured order. All-failed results request an operator alert and remain deterministic-only.
SQLite records every attempt, observed token counts/reported cost, and validated cached responses.
Unknown billed amounts remain unavailable. Cache identity binds prompt content, provider/model
order, market/evidence payload and risk decision. Prompts are versioned files and never promote
parameters. External provider verification is deferred in OPERATOR_SETUP.md.

Provider wire formats were checked against official documentation:
- https://console.groq.com/docs/structured-outputs
- https://ai.google.dev/gemini-api/docs/openai
- https://openrouter.ai/docs/api/reference/overview

The JSON request mode does not replace local schema validation. Current review/cache work is
single-worker; concurrent paid-call deduplication is not claimed.

## Layer 7 durable execution and reconciliation

`forex verify-execution` checks reservation/restart behavior in a disposable offline fixture.
It never connects to MT5. The execution service rechecks fresh quotes, broker portfolio and
Layer 5 risk after Layer 6 review, and respects both reviewed volume and money-risk ceilings.
A unique account/candidate identity is reserved transactionally before submission. Only one
unresolved submission may be in flight; unknown results block subsequent entries. Startup
reconciliation uses broker positions, orders and deals. Absent history is not proof of rejection
and never permits an automatic resend. Partial fills are reconciled, not topped up automatically.

The separate MT5ExecutionBroker is disabled by default and refuses all real-money accounts.
Its base MT5Broker stays read-only. The guarded demo transport checks runtime account/symbol/
volume/stop/freeze constraints, handles filling flags correctly, and retries filling mode only
after a definitive unsupported-fill rejection. It never retries an ambiguous order response.
Protective modifications cannot loosen stops; closing explicitly names a current bot ticket.
Manual positions are included in portfolio risk but never silently modified/closed. An existing
netting position on the symbol blocks a new entry pending explicit reconciliation.

Demo/network/retcode behavior remains unverified outside mocks. Quote changes between risk
calculation and submission are rejected; slippage tolerance is not guessed. The operator must
choose the daily session boundary before an unattended runtime. Flattening manual positions
requires a separate explicit scope decision; this transport manages bot positions only.

MT5 protocol references (not market assumptions):
- https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py
- https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants
- https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes

## Layer 8 journal, attribution and cloud mirror

`forex verify-journal` checks the local journal/outbox using a disposable offline fixture.
Every candidate, no-trade, analytical rejection, hard risk block, context verdict, execution and
outcome can be retained with complete structured provenance. Caller-supplied stable identities
must include run/version identity. Duplicate payloads are idempotent; conflicting facts under
one identity are rejected. Local event, aggregate, reserve-ledger and outbox writes are atomic.
Cloud failure is handled by a separate worker with persistent retry state. Repeated delivery
uses deterministic document IDs; reconciliation requeues missing or mismatched cloud events.

PAPER and DEMO records/aggregates are separate. The configurable profit reserve is an exact
accounting estimate on positive realized P&L, not a tax determination. Negative outcomes accrue
zero new reserve. CSV export retains the full audit payload and neutralizes spreadsheet-formula
prefixes. No account/cost metric is silently inferred from normalized research R.

Attribution produces multiple evidence-referenced observations. It separates hard risk blocks,
analytical no-candidate states, ambiguous paths, recorded stop exits and observed regime changes.
Observations are not causal proof, probabilities are not invented, and attribution cannot
change risk/strategy or block trading. Later learning must test hypotheses separately.

The optional Firestore Admin mirror writes immutable event IDs and precomputed all-time/daily
aggregates in batches. It is not called on the decision path. Install Firebase Admin only when
enabling this integration, configure project/credential path locally, and follow OPERATOR_SETUP.md.
`firestore.rules` denies all browser writes and grants PAPER/DEMO reads only to the authenticated
UID in the Admin-created `access/operator` document. Missing configuration denies access.
The Admin SDK bypasses client rules; its credential stays on the VPS and needs IAM controls.
Rules/emulator/cloud deployment remain unverified until their explicit checks run.
