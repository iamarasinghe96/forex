# Operator runbook

> Current delivery: Layer 4 read-only historical research. The software cannot trade. Instructions for unattended trading,
> remote flattening, backups, service recovery, and updates will be completed in their owning layers.

## First-time setup and verification

Follow `README.md`. Keep the terminal open and connected. A successful verification resolves all
three instruments and prints their pip value per standard lot in AUD. Copy the output **without the
`.env` file** if support is needed.

## Daily operation

There is no trading operation in Layers 1–4. Run `forex verify-foundation` after an MT5 account or
broker-server change. Every console and file-log record begins with `PAPER` or `LIVE`; the supplied
configuration is `PAPER`. Run `forex verify-market-data` to refresh the idempotent SQLite history.

## Stop immediately

Layers 1–4 send no orders, so closing the PowerShell window stops them. When execution is delivered,
emergency controls will be the authenticated phone kill switch plus the broker's MT5 mobile app.
The broker app is the independent fallback if the VPS itself is unreachable.

## Alerts and recovery

- **MT5 connection failed:** open MT5, verify the account/server and internet indicator, verify the
  password locally in `.env`, and retry.
- **AutoTrading disabled / 10027:** press MT5's **Algo Trading** toolbar button, then retry.
- **Account currency mismatch:** confirm the selected account; otherwise change `account_currency`.
- **Leverage above 1:30:** do not proceed. Ask IC Markets to cap the account at 1:30.
- **Symbol not found:** Market Watch → right-click → **Show All**, then retry.
- **No live tick/conversion quote:** add the named cross to Market Watch and retry while open.
- **Empty/short history:** in MT5 select Tools → Options → Charts, increase **Max bars in chart**,
  restart MT5, open each H1/H4 chart and scroll/load history, then rerun. Reported depth is actual.
- **Stale feed:** confirm the market is open, MT5 is connected and updating, and the VPS UTC clock is
  correct. Configured H1/H4 limits are operational defaults; configured weekend hours suppress the
  normal closure but are an approximation, not a historically DST-validated session calendar.
- **Unexplained gaps:** expected weekend gaps are separately counted so Sunday reopening cannot be
  mistaken for continuous data. Investigate midweek gaps before later analysis.
- **SQLite failure:** stop the command, preserve `data/forex.sqlite3` for diagnosis, verify disk space
  and permissions, then restore a backup or move the corrupt file aside and rerun the full download.
- **Telegram delivery failed:** check its future credentials and internet access. Telegram is disabled
  by default in this layer and alert failure never changes broker state.

## Secrets: never share these

Never commit, email, screenshot, or paste `.env`, an MT5 password, Telegram token, API key, or a
Firebase service-account JSON/private key into chat. The Firebase Admin key introduced later grants
full database access and belongs only on the VPS. If one is exposed: Firebase Console → Project
settings → Service accounts → Manage service account permissions → Keys; disable/delete the leaked
key, create a replacement, install it only on the VPS, and restart the service. Rotate other exposed
credentials in their provider console immediately.

## Known Layer 2 limits

Live IC Markets verification must run on Windows because MetaTrader5 is Windows-only. Broker history
depth and the approximate weekend/DST boundary remain environment-dependent. No strategy, risk
execution, reconciliation, Firestore, dashboard, or service automation has been implemented. Do not
use this repository to trade until those layers are delivered and the paper soak is complete.

## Layer 3 stored-history verification

Run `.\.venv\Scripts\forex.exe verify-analysis` after `verify-market-data`. It is repeatable, reads
SQLite only, filters forming bars, and cannot place or modify an order. Review each pair's last closed
H1/H4 timestamps, regime, context, evidence and candidate/no-candidate explanation. `UNAVAILABLE`
macro is expected until a later genuine provider exists and is not an error or technical veto.

If the command reports missing, insufficient, or stale candles, open and connect MT5 and run
`.\.venv\Scripts\forex.exe verify-market-data`, then rerun analysis. Do not pad history. The current
roughly 0.74-year broker sample is sufficient to exercise analysis but cannot validate an edge; the
five-year historical/backtest requirement belongs to Layer 4.

## Future closed-loop contract

Snapshots deliberately retain rejected/non-triggered opportunities as well as candidates. Later
performance intelligence can join versions and deterministic IDs to outcomes and price paths, infer
multi-label evidence-backed attribution (including regime change, signal failure, timing, false
breakout, volatility/macro shock, spread/slippage and normal variance), and evaluate counterfactual
filter value without routine manual post-trade tagging.

That future learning component is analytical/research infrastructure, **not a reactive trade blocker**.
Recent losses cannot directly veto a trade, reduce every score, disable a setup, or mutate live weights.
Any behavior change must pass versioned historical, walk-forward, out-of-sample and shadow/paper
validation before promotion. It must detect over-conservatism and under-trading by studying rejected
opportunities, not optimize merely for fewer losses. No learning engine is implemented in Layer 3.
# Layer 4 historical research runbook

Layer 4 is offline and read-only. First populate SQLite on the Windows VPS with
`forex verify-market-data`; replay itself does not connect to MT5 and imports no order API.

## Windows PowerShell verification

```powershell
git rev-parse HEAD
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[mt5,dev]"
.\.venv\Scripts\forex.exe verify-foundation
.\.venv\Scripts\forex.exe verify-market-data
.\.venv\Scripts\forex.exe verify-analysis
.\.venv\Scripts\forex.exe verify-backtest
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
Get-Content .\reports\backtest\strategy-baseline.json
.\.venv\Scripts\forex.exe validate-backtest
```

The final command is expected to return exit code 3 on the current approximately 0.74-year dataset and
print `INSUFFICIENT HISTORY FOR FIVE-YEAR VALIDATION`. `verify-backtest` should return zero if replay
and reporting work. Do not interpret this shorter engine verification as strategy/OOS/cost validation.

## Outputs and interpretation

The CLI excludes the configured final holdout from baseline decisions and outcomes. Its
`walk_forward_protocol` describes planned windows; `assumptions.walk_forward_executed` is false.
Do not report these baseline metrics as walk-forward/OOS results. A zero validation-command exit
code is a history-depth/engine result only. Fixed UTC external H4 alignment, missing execution
costs, and unresolved history gaps still require separate assessment before formal validation.

`reports/backtest/strategy-baseline.json` contains coverage gates, strategy/parameter versions,
raw candidate, setup-episode, and completed independent-simulation counts, gross and known-cost
metrics, breakdowns, rejection counts, Monte
Carlo summaries, assumptions, and warnings. Console output is the concise operator view. Re-running
with unchanged database/config produces identical analytical values; the report's timestamp is derived
from stored evaluation time, not wall-clock time.

Interpret raw candidate evaluations, setup episodes, and completed independent candidate simulations
as distinct research counts; none predicts the final live-order count. Review `simulation_status_counts`
for `NO_NEXT_BAR`, `NON_POSITIVE_INITIAL_RISK`, and `WINDOW_BOUNDARY_CENSORED` attribution. Fold-boundary
censoring is excluded from expectancy and prevents train/test/holdout prices crossing research windows.

When history is missing, run `verify-market-data` with MT5 connected, increase **Max bars in chart** if
appropriate, load the required H1/H4 charts, and rerun. Never pad, duplicate, interpolate, scrape, or
buy data as part of this workflow. If history remains below five years, preserve the report and wait
for a verified broker-neutral `Candle` source. Formal validation remains refused.

Parameter experiments must be bounded code/config inputs with a stable research identity. They do not
rewrite `config.yaml`. Walk-forward research uses research data for train windows, later test folds as
OOS observations, and excludes the final holdout. Do not repeatedly inspect that holdout. Compare
expectancy, drawdown, frequency, pair/regime stability, adjacent values, and cost sensitivity rather
than selecting highest profit or win rate. No automatic promotion exists.

OHLC ambiguity defaults to adverse stop-first. Next-bar open is the entry assumption. Breakeven and
trailing changes activate only after a bar. Commission, slippage, swap, and other fees are unavailable;
spread needs captured point metadata and remains only a candle-level approximation. Consequently gross
and net-known-cost metrics are research measurements, not realistic-complete-cost profitability.

## Verify Layer 5 risk policy (read-only)

1. Refresh stored candles with `forex verify-market-data` while MT5 is available.
2. Run `forex verify-risk --config config.yaml`.
3. Confirm each candidate summary identifies conviction/band, balance budget, executable
   bid/ask reference, structural stop, 1.5R objective, down-rounded broker volume, actual risk,
   validity, status, and reasons. No candidate is a normal result.
4. Confirm `PORTFOLIO CHECK` uses a **zero-open-position verification fixture** and
   `DAILY CIRCUIT-BREAKER CHECK` sets session opening balance to current balance without
   inferring a production latch. It must end with
   `stored/current read-only data only; no order was sent.` Real open-position
   reconciliation, flattening, breakeven, and trailing execution are reserved for Layer 7.

The daily risk-session ID and its reset boundary must be supplied explicitly by a future
runtime. Persist a triggered latch and operator kill-switch with `RiskSessionStore`; never use
that table as the authority for open MT5 positions. Circuit-breaker and kill-switch reasons are
separate, although both require new-entry halt plus flatten intent. The circuit latch cannot be
cleared by equity recovery within the same session.
The first opening balance stored for a session ID is authoritative and cannot be replaced by a
later write; start a new explicit session ID to establish another opening balance.

## Dedicated research-history import

Obtain genuine H1 CSV files from a provider whose identity, licence, timezone and price semantics you
independently verified; this project intentionally nominates no unverified vendor. Repeat import for
EURUSD, GBPUSD and USDJPY with one release/provider/database and an explicit alignment policy:

```powershell
.\.venv\Scripts\forex.exe import-history --research-database data\research.sqlite3 --file C:\verified-data\EURUSD.csv --dataset RELEASE_ID --provider PROVIDER --symbol EURUSD --price-type midpoint --volume-semantics unavailable --h4-alignment-hour-utc 0
.\.venv\Scripts\forex.exe verify-history --research-database data\research.sqlite3 --config config.yaml
.\.venv\Scripts\forex.exe validate-backtest --research-database data\research.sqlite3 --config config.yaml
```

Use `--spread-available` only with documented spread semantics. Review coverage, counts, expected
closures and unexplained gaps. Keep the IC Markets database unchanged. A conflict requires a separate
database, never an overwrite. Exit code 3 remains the insufficient-history result; eligibility is not
strategy approval.
Import is atomic across H1, H4 and provenance. Re-importing the same bytes and metadata is a no-op that
retains the first import timestamp; metadata conflicts fail. `verify-history` refuses missing or mixed
provenance, and research replay produces a fingerprinted report rather than replacing
`strategy-baseline.json`.

## Layer 6 local verification

Run `.\.venv\Scripts\forex.exe verify-context`. Expected local status is
LOCAL_CONFIGURATION_AND_SCHEMA_VERIFIED with external_provider_verification NOT_RUN.
Configure model IDs and local FOREX_GROQ_API_KEY, FOREX_GEMINI_API_KEY,
FOREX_OPENROUTER_API_KEY only when ready. Never paste the keys into chat. An all-provider
failure is deterministic-only degradation; it cannot unblock a Layer 5 rejection. The future
runtime must recheck live risk/state after a potentially slow review before any execution.

## Layer 7 recovery

Run `.\.venv\Scripts\forex.exe verify-execution` for an offline check. Success does not verify
MT5. UNKNOWN/IN_FLIGHT means an order may already exist: reconnect, query positions/orders/deals,
and reconcile. Never delete its record or resend it because the response was lost. Broker comments
may be truncated/changed; if identity cannot be established, keep the submission blocked for review.
Check Algo Trading for 10027; close-only 10044 is a broker restriction, not a Python error.
The demo adapter is intentionally not wired to an automatic order CLI. Real-money transport is
refused. Do not enable unattended broker execution before the full paper soak and manual checks.

## Layer 8 sync recovery

Run `.\.venv\Scripts\forex.exe verify-journal`. Cloud is deliberately disabled by default.
An outage leaves journal events/outbox rows in SQLite. Restart the sync worker; do not delete
records or rebuild trade state from Firestore. A failed cloud write may already have succeeded:
retry uses the same document ID. Reconcile remote hashes in bounded pages and requeue divergence.
Back up SQLite with its backup API rather than copying a live WAL database file.

Before enabling cloud: configure a Firebase project, create the operator Auth UID, deploy/review
rules and indexes, create `access/operator` with that UID using Admin privileges, and run allowed-
UID/other-UID/anonymous/write-denial emulator tests. Keep the service-account file on the VPS.
