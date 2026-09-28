# Operator runbook

> Current delivery: Layer 1 only. The software cannot trade. Instructions for unattended trading,
> remote flattening, backups, service recovery, and updates will be completed in their owning layers.

## First-time setup and verification

Follow `README.md`. Keep the terminal open and connected. A successful verification resolves all
three instruments and prints their pip value per standard lot in AUD. Copy the output **without the
`.env` file** if support is needed.

## Daily operation

There is no daily trading operation in Layer 1. Run `forex verify-foundation` after an MT5 account or
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
- **Telegram delivery failed:** check its future credentials and internet access. Telegram is disabled
  by default in this layer and alert failure never changes broker state.

## Secrets: never share these

Never commit, email, screenshot, or paste `.env`, an MT5 password, Telegram token, API key, or a
Firebase service-account JSON/private key into chat. The Firebase Admin key introduced later grants
full database access and belongs only on the VPS. If one is exposed: Firebase Console → Project
settings → Service accounts → Manage service account permissions → Keys; disable/delete the leaked
key, create a replacement, install it only on the VPS, and restart the service. Rotate other exposed
credentials in their provider console immediately.

## Known Layer 1 limits

Live IC Markets verification must run on Windows because MetaTrader5 is Windows-only. No market
data history, strategy, risk execution, reconciliation, Firestore, dashboard, or service automation
has been implemented yet. Do not use this repository to trade until those layers are delivered and
the paper soak is complete.
