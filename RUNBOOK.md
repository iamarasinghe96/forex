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

`reports/backtest/strategy-baseline.json` contains coverage gates, strategy/parameter versions,
evaluation/candidate/trade counts, gross and known-cost metrics, breakdowns, rejection counts, Monte
Carlo summaries, assumptions, and warnings. Console output is the concise operator view. Re-running
with unchanged database/config produces identical analytical values; the report's timestamp is derived
from stored evaluation time, not wall-clock time.

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
