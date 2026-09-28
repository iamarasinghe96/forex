# Operator runbook

> Current delivery: Layers 1–2 only. The software cannot trade. Instructions for unattended trading,
> remote flattening, backups, service recovery, and updates will be completed in their owning layers.

## First-time setup and verification

Follow `README.md`. Keep the terminal open and connected. A successful verification resolves all
three instruments and prints their pip value per standard lot in AUD. Copy the output **without the
`.env` file** if support is needed.

Then run `.venv\Scripts\forex verify-market-data`. Success reports H1 and H4 history boundaries for
EURUSD, GBPUSD, and USDJPY, persists/reloads those bars, and explicitly says no order was sent.

## Daily operation

There is no daily trading operation yet. Run `forex verify-foundation` after an MT5 account or
broker-server change. Every console and file-log record begins with `PAPER` or `LIVE`; the supplied
configuration is `PAPER`.

## Stop immediately

Layer 1 sends no orders, so closing the PowerShell window stops it. When execution is delivered,
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
- **Stale market data:** do not use the feed. Confirm the lower-right MT5 connection indicator is
  active and Market Watch prices are changing; open the affected chart, then rerun verification.
- **No bars after bounded retries:** in MT5 use Tools → Options → Charts to increase **Max bars in
  chart**, open the affected H1/H4 chart to trigger loading, wait briefly, and rerun.
- **Unexplained gap:** MT5 omitted one or more scheduled bars outside the normal weekend closure.
  Refresh the named chart and rerun. Expected weekend gaps are informational and need no action.
- **Less than five years:** this is not a Layer 2 failure. Save the reported earliest/latest dates;
  Layer 4 will determine the exact external-history shortfall without adding a paid source now.
- **SQLite verification failed:** confirm the VPS disk has free space and this folder is writable,
  then rerun. The upsert is transactional, so a failed transaction does not leave half a batch.
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

Live history depth is knowable only from the connected Windows MT5 terminal. No strategy, sentiment,
regime detection, risk execution, reconciliation, Firestore, dashboard, or service automation has
been implemented. Do not use this repository to trade until those layers and the paper soak are
complete.
